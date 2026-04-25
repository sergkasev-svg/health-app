from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from app.services.consultation_assistant import run_consultation_turn
from app.services.integration_bridge import bridge_status as get_bridge_runtime_status
from app.services.mikhail_knowledge_retrieval import rag_index_snippets_for_tooling, unified_knowledge_search
from app.services.medication_lookup import route_medication_lookup
from app.services.red_flag_screening import ambulance_offer_flow_payload, is_emergency_call_intent
from app.services.user_store import (
    add_calendar_reminder,
    add_notification,
    get_calendar_reminders,
    get_chat_history,
    get_documents,
    get_lab_cases,
    get_profile,
    get_symptom_entries,
    get_vitals,
)

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_RAG_INDEX_FILE = _BACKEND_DIR / "app" / "knowledge" / "rag" / "mikhail_rag_index.jsonl"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    t = _norm(text)
    return any(w in t for w in words)


@dataclass
class ToolResult:
    name: str
    payload: dict[str, Any]


class MikhailWorker:
    """Production-safe tool orchestrator.

    Uses current app knowledge first, then bridge/v2, then RAG index file.
    Never replaces core consultation flow; only enriches context.
    """

    # ---------------------- tools ----------------------
    def search_knowledge(self, query: str, *, top_k: int = 10) -> dict[str, Any]:
        bundle = unified_knowledge_search(query, final_items=max(top_k, 10))
        merged = list(bundle.get("items") or [])
        med = route_medication_lookup(query)
        medication_hint = str((med or {}).get("response_simple") or "").strip() if isinstance(med, dict) else ""

        rag_hits = rag_index_snippets_for_tooling(query, top_k=max(8, top_k))

        return {
            "query": query,
            "items": merged,
            "medication_hint": medication_hint[:800],
            "rag_hits": rag_hits,
            "deduped_count": int(len(merged)),
            "retrieval_meta": {
                "recall_raw_count": bundle.get("recall_raw_count"),
                "after_filter_count": bundle.get("after_filter_count"),
                "final_count": bundle.get("final_count"),
            },
        }

    def get_user_lab_results(self, user_id: str, *, subject_id: str | None = None) -> dict[str, Any]:
        cases = get_lab_cases(user_id, subject_id=subject_id)
        docs = get_documents(user_id, subject_id=subject_id)
        lab_docs = [
            d
            for d in docs
            if "анализ" in _norm(str(d.get("title") or ""))
            or "lab" in _norm(str(d.get("title") or ""))
            or "анализ" in _norm(str(d.get("filename") or ""))
        ]
        return {
            "cases_total": len(cases),
            "recent_cases": [str((x or {}).get("name") or "") for x in cases[-3:]],
            "lab_documents_total": len(lab_docs),
            "lab_documents_recent": [str((x or {}).get("title") or x.get("filename") or "") for x in lab_docs[-3:]],
        }

    def set_reminder(self, user_id: str, medication: str, time_text: str, *, frequency: str = "daily") -> dict[str, Any]:
        medication_s = (medication or "").strip() or "добавки"
        time_s = (time_text or "").strip() or "в удобное время"
        freq_s = (frequency or "").strip() or "daily"
        body = f"Напоминание: {medication_s} — {time_s} ({freq_s})."
        reminder = add_calendar_reminder(
            user_id=user_id,
            title=f"Приём: {medication_s}",
            schedule_time=time_s,
            frequency=freq_s,
            payload={"medication": medication_s, "source": "mikhail_worker"},
            active=True,
        )
        item = add_notification(
            user_id=user_id,
            title="Напоминание о приёме",
            body=body,
            unread=True,
            action={"type": "medication_reminder", "medication": medication_s, "time": time_s, "frequency": freq_s},
        )
        return {
            "created": True,
            "calendar_reminder_id": reminder.get("id"),
            "notification_id": item.get("id"),
            "body": body,
        }

    def call_emergency(self, user_id: str, message: str) -> dict[str, Any]:
        profile = get_profile(user_id)
        address = str(profile.get("address") or profile.get("city") or "").strip()
        emergency_payload = ambulance_offer_flow_payload(message or "")
        add_notification(
            user_id=user_id,
            title="Экстренная рекомендация",
            body=f"Рекомендуется вызвать 103. Адрес профиля: {address or 'не указан'}.",
            unread=True,
            action={"type": "emergency_call_suggested"},
        )
        return {"recommended": True, "address": address, "payload": emergency_payload}

    def pubmed_search(self, query: str, *, max_results: int = 3) -> dict[str, Any]:
        """NCBI E-utilities search (no extra deps)."""
        q = str(query or "").strip()
        if not q:
            return {"ok": False, "error": "empty_query", "items": []}
        email = os.getenv("PUBMED_EMAIL", "").strip()
        tool = "za-zdorovie-mikhail"
        try:
            s = requests.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={
                    "db": "pubmed",
                    "term": q,
                    "retmode": "json",
                    "retmax": max(1, min(int(max_results), 10)),
                    "tool": tool,
                    "email": email,
                },
                timeout=10,
            )
            s.raise_for_status()
            ids = ((s.json() or {}).get("esearchresult") or {}).get("idlist") or []
            if not ids:
                return {"ok": True, "items": []}
            summ = requests.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                params={
                    "db": "pubmed",
                    "id": ",".join(ids),
                    "retmode": "json",
                    "tool": tool,
                    "email": email,
                },
                timeout=10,
            )
            summ.raise_for_status()
            payload = summ.json() or {}
            res = payload.get("result") or {}
            items: list[dict[str, Any]] = []
            for pid in ids:
                row = res.get(str(pid)) or {}
                title = str(row.get("title") or "").strip()
                if not title:
                    continue
                items.append(
                    {
                        "pmid": str(pid),
                        "title": title,
                        "pubdate": str(row.get("pubdate") or "").strip(),
                        "source": str(row.get("source") or "").strip(),
                        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
                    }
                )
            return {"ok": True, "items": items}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "items": []}

    def official_dose_lookup(self, query: str) -> dict[str, Any]:
        """Dose adapter with safe fallback: medication handbook -> PubMed -> conservative guidance."""
        med = route_medication_lookup(query)
        if isinstance(med, dict) and str(med.get("response_simple") or "").strip():
            return {
                "ok": True,
                "source": "internal_medication_handbook",
                "summary": str(med.get("response_simple") or "").strip(),
                "safety": "Дозы и схемы — по инструкции к конкретному препарату и с учётом противопоказаний.",
            }
        pub = self.pubmed_search(query, max_results=3)
        if pub.get("ok") and (pub.get("items") or []):
            refs = [f"{x.get('title')} ({x.get('url')})" for x in (pub.get("items") or [])[:3]]
            return {
                "ok": True,
                "source": "pubmed",
                "summary": "Найдено несколько актуальных публикаций по теме дозировок/эффектов.",
                "references": refs,
                "safety": "Назначение и точные дозировки должен подтверждать врач.",
            }
        return {
            "ok": True,
            "source": "safe_fallback",
            "summary": "Точной дозировки по вашему запросу в подключённых источниках сейчас не найдено.",
            "safety": "Используйте только официальную инструкцию и консультацию врача, особенно для детей, беременности и хронических болезней.",
        }

    def tool_catalog(self) -> list[dict[str, str]]:
        return [
            {"name": "search_knowledge", "purpose": "Поиск по объединённой базе знаний и RAG"},
            {"name": "get_user_lab_results", "purpose": "Получить последние лабораторные данные пользователя"},
            {"name": "set_reminder", "purpose": "Создать календарное напоминание + уведомление"},
            {"name": "call_emergency", "purpose": "Экстренный сценарий с адресом профиля"},
            {"name": "pubmed_search", "purpose": "Поиск актуальных публикаций PubMed"},
            {"name": "official_dose_lookup", "purpose": "Проверка дозировок с безопасным fallback"},
        ]

    def status(self, user_id: str | None = None) -> dict[str, Any]:
        bridge = get_bridge_runtime_status()
        rag_ready = _RAG_INDEX_FILE.is_file()
        pubmed_email = bool(os.getenv("PUBMED_EMAIL", "").strip())
        sample_reminders = []
        if user_id:
            try:
                sample_reminders = get_calendar_reminders(user_id)[-3:]
            except Exception:
                sample_reminders = []
        return {
            "tools": self.tool_catalog(),
            "bridge": bridge,
            "rag_index": {"ready": rag_ready, "path": str(_RAG_INDEX_FILE)},
            "pubmed": {"configured": pubmed_email},
            "calendar_reminders_sample": sample_reminders,
        }

    # ---------------------- chat orchestration ----------------------
    async def chat(
        self,
        *,
        user_id: str,
        message: str,
        subject_id: str | None = None,
        app_mode: str | None = None,
    ) -> dict[str, Any]:
        profile = get_profile(user_id)
        vitals = get_vitals(user_id, subject_id=subject_id)
        symptom_entries = get_symptom_entries(user_id, subject_id=subject_id)
        chat_history = get_chat_history(user_id, subject_id=subject_id)
        docs = get_documents(user_id, subject_id=subject_id)

        tools_used: list[ToolResult] = []
        knowledge = self.search_knowledge(message, top_k=10)
        tools_used.append(ToolResult(name="search_knowledge", payload=knowledge))

        if _contains_any(message, ("анализ", "ферритин", "витамин d", "лаб", "лаборат", "гемоглобин", "ттг")):
            tools_used.append(
                ToolResult(
                    name="get_user_lab_results",
                    payload=self.get_user_lab_results(user_id=user_id, subject_id=subject_id),
                )
            )

        if _contains_any(message, ("напомни", "напоминание", "календар", "время приема", "прием добавок")):
            tools_used.append(
                ToolResult(
                    name="set_reminder",
                    payload=self.set_reminder(
                        user_id=user_id,
                        medication="добавки/лекарства",
                        time_text="ежедневно",
                        frequency="daily",
                    ),
                )
            )

        if _contains_any(message, ("pubmed", "исследован", "статья", "протокол", "guideline", "доказательств")):
            tools_used.append(ToolResult(name="pubmed_search", payload=self.pubmed_search(message, max_results=3)))
        if _contains_any(message, ("дозиров", "сколько мг", "какая доза", "как принимать", "dose")):
            tools_used.append(ToolResult(name="official_dose_lookup", payload=self.official_dose_lookup(message)))

        if is_emergency_call_intent(message):
            tools_used.append(ToolResult(name="call_emergency", payload=self.call_emergency(user_id=user_id, message=message)))

        tool_context_lines = []
        if knowledge.get("items"):
            tool_context_lines.append("Knowledge hits:")
            for x in knowledge["items"][:8]:
                desc = str(x.get("description") or "").strip()
                tail = (desc[:200] + "…") if len(desc) > 200 else desc
                tool_context_lines.append(f"- {x.get('title')} ({x.get('source')}) {tail}".strip())
        if knowledge.get("medication_hint"):
            tool_context_lines.append("Medication hint:")
            tool_context_lines.append(str(knowledge["medication_hint"]))
        for t in tools_used:
            if t.name == "pubmed_search" and isinstance(t.payload, dict) and t.payload.get("ok"):
                pubs = t.payload.get("items") or []
                if pubs:
                    tool_context_lines.append("PubMed recent:")
                    for p in pubs[:2]:
                        tool_context_lines.append(f"- {p.get('title')} ({p.get('url')})")
        document_context = "\n".join(tool_context_lines).strip() or None

        result = await run_consultation_turn(
            user_id=user_id,
            user_message=message,
            profile=profile,
            documents_count=len(docs),
            symptom_entries=symptom_entries,
            chat_history=chat_history,
            app_mode=app_mode,
            vitals=vitals,
            document_context=document_context,
            subject_id=subject_id,
        )
        result["tool_layer"] = {
            "tools_used": [{"name": t.name, "payload": t.payload} for t in tools_used],
            "knowledge_deduped_count": int(knowledge.get("deduped_count") or 0),
            "available_tools": self.tool_catalog(),
        }
        return result

    # ---------------------- internal helpers ----------------------
