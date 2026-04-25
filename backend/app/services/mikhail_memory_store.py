"""
Хранилище памяти сессии Михаила: file-based JSON или in-memory fallback.
Безопасно: при недоступности хранилища не падаем, работаем in-memory.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from app.services.mikhail_memory import MikhailSessionMemory


def _default_path(user_id: Optional[str], session_id: Optional[str]) -> Optional[Path]:
    """Путь к файлу памяти: data/users/<user_id>/mikhail_memory_<session_id>.json."""
    try:
        base = Path(__file__).resolve().parent.parent.parent / "data" / "users"
        safe_uid = "".join(c if c.isalnum() or c in "-_" else "_" for c in (user_id or "default").strip())[:64] or "default"
        sid = (session_id or "main").strip() or "main"
        safe_sid = "".join(c for c in sid if c.isalnum() or c in "-_")[:40] or "main"
        return base / safe_uid / f"mikhail_memory_{safe_sid}.json"
    except Exception:
        return None


class MikhailMemoryStore:
    """
    Load/save/merge памяти сессии.
    File-based при наличии пути; иначе in-memory fallback.
    """

    def __init__(
        self,
        file_path_builder: Optional[Callable[[Optional[str], Optional[str]], Optional[Path]]] = None,
    ):
        self._path_builder = file_path_builder or _default_path
        self._memory: Dict[str, MikhailSessionMemory] = {}

    def _key(self, user_id: Optional[str], session_id: Optional[str]) -> str:
        return f"{user_id or 'default'}:{session_id or 'main'}"

    def load(self, user_id: Optional[str], session_id: Optional[str]) -> MikhailSessionMemory:
        """Загрузить память сессии. При ошибке — пустая память."""
        key = self._key(user_id, session_id)
        path = self._path_builder(user_id, session_id) if self._path_builder else None
        if path and path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                mem = MikhailSessionMemory.from_dict(data)
                mem.user_id = user_id
                mem.session_id = session_id
                self._memory[key] = mem
                return mem
            except Exception:
                pass
        if key in self._memory:
            return self._memory[key]
        return MikhailSessionMemory(session_id=session_id, user_id=user_id)

    def save(self, memory: MikhailSessionMemory) -> None:
        """Сохранить память. При ошибке — только in-memory."""
        if not memory:
            return
        key = self._key(memory.user_id, memory.session_id)
        memory.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._memory[key] = memory
        path = self._path_builder(memory.user_id, memory.session_id) if self._path_builder else None
        if path:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(memory.to_dict(), f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    def merge(
        self,
        old_memory: MikhailSessionMemory,
        new_data: Dict[str, Any],
    ) -> MikhailSessionMemory:
        """
        Объединить старую память с новыми данными.
        Симптомы: дедупликация, обновление last_seen_at.
        Лабы: добавляем новые, не теряем старые.
        Asked questions: добавляем новые, помечаем ответы при наличии.
        Follow-up plan: обновляем из new_data если передан.
        """
        from app.services.mikhail_memory import (
            AskedQuestionRecord,
            FollowUpPlan,
            LabRecord,
            SymptomRecord,
        )

        out = MikhailSessionMemory(
            session_id=old_memory.session_id,
            user_id=old_memory.user_id,
            symptoms=list(old_memory.symptoms),
            labs=list(old_memory.labs),
            asked_questions=list(old_memory.asked_questions),
            hypotheses_history=list(old_memory.hypotheses_history),
            prior_states=list(old_memory.prior_states),
            uploaded_files=list(old_memory.uploaded_files),
            follow_up_plan=FollowUpPlan.from_dict(old_memory.follow_up_plan.to_dict()) if old_memory.follow_up_plan else None,
            last_summary=old_memory.last_summary,
            updated_at=old_memory.updated_at,
        )
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Symptoms: merge by name (lower), no duplicates
        new_symptoms = new_data.get("symptoms") or []
        if isinstance(new_symptoms, list):
            name_to_record = {s.name.strip().lower(): s for s in out.symptoms if s.name}
            for s in new_symptoms:
                if isinstance(s, SymptomRecord):
                    name = s.name.strip().lower()
                else:
                    name = str(s).strip().lower() if s else ""
                if not name:
                    continue
                if name in name_to_record:
                    name_to_record[name].last_seen_at = now
                    if isinstance(s, SymptomRecord):
                        if s.severity:
                            name_to_record[name].severity = s.severity
                        if s.status:
                            name_to_record[name].status = s.status
                else:
                    rec = SymptomRecord(name=name, first_seen_at=now, last_seen_at=now, source=new_data.get("source")) if not isinstance(s, SymptomRecord) else s
                    if isinstance(s, SymptomRecord) and not rec.last_seen_at:
                        rec.last_seen_at = now
                    name_to_record[name] = rec
            out.symptoms = list(name_to_record.values())

        # Labs: append new records
        new_labs = new_data.get("labs") or []
        for row in new_labs:
            if isinstance(row, LabRecord):
                out.labs.append(row)
            elif isinstance(row, dict) and (row.get("marker_name") or row.get("title") or row.get("name")):
                out.labs.append(
                    LabRecord(
                        marker_name=str(row.get("marker_name") or row.get("title") or row.get("name") or "").strip(),
                        value=_f(row.get("value")),
                        unit=row.get("unit"),
                        ref_low=_f(row.get("ref_low")),
                        ref_high=_f(row.get("ref_high")),
                        flag=row.get("flag"),
                        date=row.get("date") or now[:10],
                        source_file=row.get("source_file"),
                    )
                )
        out.labs = out.labs[-100:]

        # Asked questions: add new, mark answered if answer in new_data
        answered_summaries = new_data.get("answered_questions") or {}
        for q in out.asked_questions:
            qtext = (q.question or "").strip().lower()
            if qtext and qtext in answered_summaries:
                q.answered = True
                q.answer_summary = answered_summaries.get(qtext)
        new_asked = new_data.get("asked_questions") or []
        for q in new_asked:
            text = (q.get("question") if isinstance(q, dict) else str(q)).strip()
            if not text:
                continue
            if not any((a.question or "").strip().lower() == text.lower() for a in out.asked_questions):
                out.asked_questions.append(
                    AskedQuestionRecord(question=text, asked_at=now, answered=False)
                    if isinstance(q, dict)
                    else AskedQuestionRecord(question=text, asked_at=now, answered=False)
                )
        out.asked_questions = out.asked_questions[-30:]

        # Prior state
        if new_data.get("state"):
            out.prior_states = (out.prior_states + [str(new_data["state"])])[-10:]

        # Hypotheses history (compact)
        if new_data.get("hypotheses"):
            out.hypotheses_history = (out.hypotheses_history + [{"summary": [h.get("name") for h in new_data["hypotheses"][:3]]}])[-20:]

        # Follow-up plan
        if new_data.get("follow_up_plan"):
            out.follow_up_plan = FollowUpPlan.from_dict(new_data["follow_up_plan"])

        return out


def _f(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
