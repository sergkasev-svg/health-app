from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from app.medical_core.engine import MedicalCoreEngine
except Exception:  # optional overlay
    MedicalCoreEngine = None  # type: ignore


CARE_LEVEL_ORDER = {
    "self_care": 0,
    "planned_consult": 1,
    "same_day": 2,
    "urgent": 3,
    "emergency": 4,
    "emergency_ambulance": 5,
}


@dataclass
class SelectorResult:
    matched: bool
    entry_id: str = ""
    entry_name: str = ""
    entry_type: str = ""
    score_hint: float = 0.0
    triage_level: str = "planned_consult"
    triage_target: str = "outpatient"
    red_flags: list[str] | None = None
    best_question: str = ""
    candidate_diseases: list[dict[str, Any]] | None = None
    first_line: list[str] | None = None
    tests: list[str] | None = None
    nutrition: list[str] | None = None
    activity: list[str] | None = None
    specialist: str = ""
    reasoning: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "entry_id": self.entry_id,
            "entry_name": self.entry_name,
            "entry_type": self.entry_type,
            "score_hint": self.score_hint,
            "triage_level": self.triage_level,
            "triage_target": self.triage_target,
            "red_flags": list(self.red_flags or []),
            "best_question": self.best_question,
            "candidate_diseases": list(self.candidate_diseases or []),
            "first_line": list(self.first_line or []),
            "tests": list(self.tests or []),
            "nutrition": list(self.nutrition or []),
            "activity": list(self.activity or []),
            "specialist": self.specialist,
            "reasoning": dict(self.reasoning or {}),
        }


def _safe_list(value: Any, limit: int = 5) -> list[str]:
    out: list[str] = []
    for x in value or []:
        s = str(x or "").strip()
        if s:
            out.append(s)
    return out[:limit]


def _specialist_from_entry(entry: dict[str, Any]) -> str:
    route = (entry.get("route") or {}) if isinstance(entry, dict) else {}
    specialist = str(route.get("specialist") or "").strip()
    if specialist:
        return specialist
    category = str(entry.get("category") or "").lower()
    if "карди" in category or "давлен" in category:
        return "Кардиолог"
    if "жкт" in category or "гастро" in category:
        return "Гастроэнтеролог"
    if "лор" in category:
        return "ЛОР"
    if "кожа" in category:
        return "Дерматолог"
    if "невро" in category or "голов" in category:
        return "Невролог"
    if "жен" in category or "гин" in category:
        return "Гинеколог"
    return "Терапевт"


class MedicalCoreSelector:
    """Early complaint/condition selector using medical_core."""

    def __init__(self, engine: Any | None = None) -> None:
        self.engine = engine or (MedicalCoreEngine() if MedicalCoreEngine else None)

    def available(self) -> bool:
        return self.engine is not None

    def select(
        self,
        *,
        user_message: str,
        symptom_context: dict[str, Any] | None = None,
        profile: dict[str, Any] | None = None,
        existing_state: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> SelectorResult:
        if not self.engine:
            return SelectorResult(matched=False)

        query = self._build_query(
            user_message=user_message,
            symptom_context=symptom_context or {},
            profile=profile or {},
            existing_state=existing_state or {},
        )
        entries = self.engine.find_best_entries(query, limit=limit) or []
        if not entries:
            return SelectorResult(matched=False)

        ranked = sorted(
            entries,
            key=lambda row: self._score_row(row, query, symptom_context or {}, profile or {}),
            reverse=True,
        )
        best = ranked[0]
        best_entry_id = str(best.get("entry_id") or "")
        plan = self.engine.complaint_plan(best_entry_id) if best_entry_id else {}
        safe = self.engine.safe_summary(best_entry_id) if best_entry_id else {}
        triage_level = str(safe.get("care_level") or "planned_consult")
        triage_target = self._triage_target(best, triage_level)
        first_question = self._best_question(best)

        return SelectorResult(
            matched=True,
            entry_id=best_entry_id,
            entry_name=str(best.get("name") or ""),
            entry_type=str(best.get("type") or ""),
            score_hint=float(self._score_row(best, query, symptom_context or {}, profile or {})),
            triage_level=triage_level,
            triage_target=triage_target,
            red_flags=_safe_list(safe.get("red_flags") or ((best.get("triage") or {}).get("red_flags") or []), limit=6),
            best_question=first_question,
            candidate_diseases=list(plan.get("candidate_diseases") or [])[:5],
            first_line=_safe_list(safe.get("first_line") or ((best.get("care") or {}).get("first_line") or []), limit=5),
            tests=_safe_list(safe.get("tests") or ((best.get("care") or {}).get("tests") or []), limit=3),
            nutrition=_safe_list(safe.get("nutrition") or ((best.get("care") or {}).get("nutrition") or []), limit=3),
            activity=_safe_list(safe.get("activity") or ((best.get("care") or {}).get("activity") or []), limit=3),
            specialist=_specialist_from_entry(best),
            reasoning={
                "query": query,
                "ranked_entry_ids": [str(x.get("entry_id") or "") for x in ranked[:3]],
                "ranked_names": [str(x.get("name") or "") for x in ranked[:3]],
                "behavior_rules": (plan.get("behavior_rules") or {}),
            },
        )

    def _build_query(
        self,
        *,
        user_message: str,
        symptom_context: dict[str, Any],
        profile: dict[str, Any],
        existing_state: dict[str, Any],
    ) -> str:
        parts: list[str] = [str(user_message or "").strip()]
        for key in ("chief_complaint", "body_location", "symptom_summary", "current_branch"):
            value = symptom_context.get(key) or existing_state.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        symptoms = symptom_context.get("symptoms") or existing_state.get("symptoms") or []
        if isinstance(symptoms, list):
            parts.extend([str(x).strip() for x in symptoms[:8] if str(x).strip()])
        for key in ("sex", "age", "pregnancy_status"):
            value = profile.get(key)
            if value not in (None, "", []):
                parts.append(f"{key}:{value}")
        return "; ".join([x for x in parts if x])

    def _score_row(self, row: dict[str, Any], query: str, symptom_context: dict[str, Any], profile: dict[str, Any]) -> float:
        score = 0.0
        q = query.lower()
        name = str(row.get("name") or "").lower()
        category = str(row.get("category") or "").lower()
        if name and name in q:
            score += 4.0
        triage = (row.get("triage") or {}) if isinstance(row, dict) else {}
        red_flags = [str(x).lower() for x in (triage.get("red_flags") or []) if str(x).strip()]
        if any(flag in q for flag in red_flags[:5]):
            score += 5.0
        for token in [category, str(symptom_context.get("body_location") or "").lower()]:
            if token and token in q:
                score += 1.5
        if profile.get("pregnancy_status") and ("берем" in name or "берем" in category):
            score += 1.5
        level = str(triage.get("recommended_care_level") or "planned_consult")
        score += CARE_LEVEL_ORDER.get(level, 1) * 0.05
        return score

    def _best_question(self, entry: dict[str, Any]) -> str:
        fu = (entry.get("follow_up") or {}) if isinstance(entry, dict) else {}
        for key in ("red_flag_questions", "must_ask", "context_questions"):
            items = [str(x).strip() for x in (fu.get(key) or []) if str(x).strip()]
            if items:
                return items[0]
        return "Как давно это началось и что усиливает или ослабляет симптомы?"

    def _triage_target(self, entry: dict[str, Any], triage_level: str) -> str:
        route = (entry.get("route") or {}) if isinstance(entry, dict) else {}
        target = str(route.get("triage_target") or "").strip()
        if target:
            return target
        if triage_level in {"emergency", "emergency_ambulance"}:
            return "urgent_care"
        if triage_level == "same_day":
            return "same_day_clinic"
        return "outpatient"

