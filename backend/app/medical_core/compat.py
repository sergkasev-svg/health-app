from __future__ import annotations

from typing import Any

from .engine import MedicalCoreEngine


def build_query_from_consultation_state(state: Any) -> str:
    try:
        parts = [str(getattr(state, "chief_complaint", "") or "")]
        history = getattr(state, "history", None)
        if history is not None:
            parts.extend(list(getattr(history, "symptoms", []) or []))
            if getattr(history, "location", None):
                parts.append(str(history.location))
        return "; ".join([x for x in parts if x])
    except Exception:
        return ""


def suggest_medical_core_entries(state: Any, limit: int = 5) -> list[dict[str, Any]]:
    engine = MedicalCoreEngine()
    query = build_query_from_consultation_state(state)
    return engine.find_best_entries(query, limit=limit)
