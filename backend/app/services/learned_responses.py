"""
Сохранение ответов онлайн (LLM) в общий справочник для последующего офлайн-использования.
Если офлайн не дал ответа — идём в OpenAI; полученный ответ сохраняем в learned_responses,
чтобы при похожем вопросе можно было ответить из справочника без повторного вызова API.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_LEARNED_FILE = _BACKEND_DIR.parent / "knowledge_cache" / "learned_responses.json"
_LEARNED_DIALOGUE_FILE = _BACKEND_DIR.parent / "medical_knowledge" / "diseases" / "learned_dialogue_cases.json"
_MAX_ENTRIES = 500
_MIN_OVERLAP = 0.35


def _norm(q: str) -> str:
    if not q or not isinstance(q, str):
        return ""
    s = re.sub(r"[^\w\sа-яёa-z0-9]", " ", q.strip().lower())
    return " ".join(w for w in s.split() if len(w) > 1)


def _load() -> list[dict[str, Any]]:
    if not _LEARNED_FILE.exists():
        return []
    try:
        data = json.loads(_LEARNED_FILE.read_text(encoding="utf-8"))
        return list(data.get("entries") or [])
    except Exception:
        return []


def _load_dialogue_cases() -> list[dict[str, Any]]:
    """Load approved cases from review queue (learned_dialogue_cases.json) for offline use."""
    if not _LEARNED_DIALOGUE_FILE.exists():
        return []
    try:
        data = json.loads(_LEARNED_DIALOGUE_FILE.read_text(encoding="utf-8"))
        items = list(data.get("items") or [])
        out: list[dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            complaint = (it.get("complaint") or "").strip()
            summary = (it.get("report_summary") or "").strip()
            care = it.get("care_plan_today") or []
            urgent = it.get("when_urgent") or []
            query_raw = (complaint + " " + summary).strip() or complaint
            if not query_raw:
                continue
            response_parts = [summary] if summary else []
            if care:
                response_parts.append("Что делать: " + "; ".join(str(x) for x in care[:5] if x))
            if urgent:
                response_parts.append("Когда срочно: " + "; ".join(str(x) for x in urgent[:4] if x))
            response = "\n".join(response_parts).strip() or "Рекомендуется уточнить симптомы и при необходимости обратиться к врачу."
            out.append({
                "query_norm": _norm(query_raw),
                "query_orig": query_raw[:400],
                "response": response[:2500],
                "response_simple": (summary or response)[:1200],
                "ts": it.get("created_at") or 0,
                "source": "learned_dialogue",
            })
        return out
    except Exception:
        return []


def _save(entries: list[dict[str, Any]]) -> None:
    _LEARNED_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "description": "Ответы, полученные через LLM; используются при похожих вопросах вместо повторного вызова API.",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(entries),
        "entries": entries,
    }
    _LEARNED_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def save_learned_response(
    query: str,
    response: str,
    response_simple: str | None = None,
    hypotheses: list[str] | None = None,
) -> None:
    """Добавить ответ в общий справочник (после успешного ответа LLM)."""
    norm = _norm(query)
    if not norm or not (response or "").strip():
        return
    entries = _load()
    new_entry = {
        "query_norm": norm,
        "query_orig": (query or "")[:400],
        "response": (response or "")[:2500],
        "response_simple": (response_simple or "")[:1200] if response_simple else None,
        "hypotheses": (hypotheses or [])[:10],
        "ts": time.time(),
    }
    entries = [e for e in entries if e.get("query_norm") != norm]
    entries.append(new_entry)
    if len(entries) > _MAX_ENTRIES:
        entries.sort(key=lambda x: x.get("ts") or 0)
        entries = entries[-_MAX_ENTRIES:]
    _save(entries)


def get_learned_responses(query: str, limit: int = 2) -> list[dict[str, Any]]:
    """Вернуть до limit наиболее похожих сохранённых ответов по запросу (для подстановки в контекст или офлайн-ответа).
    Объединяет записи из learned_responses.json и approved cases из learned_dialogue_cases.json (review queue).
    Каждый элемент содержит score (overlap 0..1) для решения, использовать ли ответ без вызова LLM."""
    norm = _norm(query)
    norm_tokens = set(norm.split()) if norm else set()
    if not norm_tokens:
        return []
    entries = _load()
    dialogue = _load_dialogue_cases()
    for d in dialogue:
        if d.get("query_norm") and d not in entries:
            entries.append(d)
    scored: list[tuple[float, dict[str, Any]]] = []
    for e in entries:
        en = (e.get("query_norm") or "").strip()
        if not en:
            continue
        et = set(en.split())
        overlap = len(norm_tokens & et) / max(len(norm_tokens), 1)
        if overlap >= _MIN_OVERLAP:
            out = dict(e)
            out["score"] = round(overlap, 3)
            scored.append((overlap, out))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:limit]]
