from __future__ import annotations

from functools import lru_cache
from typing import Any

try:
    from app.medical_core.engine import MedicalCoreEngine
    from app.medical_core.repository import MedicalCoreRepository
except Exception:  # optional overlay
    MedicalCoreEngine = None  # type: ignore[assignment]
    MedicalCoreRepository = None  # type: ignore[assignment]


def _uniq(items: list[str], limit: int | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        s = str(item or "").strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
        if limit and len(out) >= limit:
            break
    return out


@lru_cache(maxsize=1)
def _repo() -> Any:
    if MedicalCoreRepository is None:
        return None
    try:
        return MedicalCoreRepository()
    except Exception:
        return None


@lru_cache(maxsize=1)
def _engine() -> Any:
    if MedicalCoreEngine is None:
        return None
    try:
        return MedicalCoreEngine()
    except Exception:
        return None


def _care_level_rank(value: str) -> int:
    table = {
        "emergency_ambulance": 6,
        "emergency": 5,
        "urgent": 4,
        "same_day": 3,
        "planned_consult": 2,
        "self_care": 1,
    }
    return table.get(str(value or "").strip().lower(), 0)


def map_complaint_entry(entry: dict[str, Any]) -> dict[str, Any]:
    follow_up = entry.get("follow_up") or {}
    triage = entry.get("triage") or {}
    care = entry.get("care") or {}
    diag = entry.get("diagnostic_support") or {}
    return {
        "id": str(entry.get("source_id") or entry.get("entry_id") or "").strip(),
        "entry_id": str(entry.get("entry_id") or "").strip(),
        "complaint": str(entry.get("name") or "").strip(),
        "name": str(entry.get("name") or "").strip(),
        "category": str(entry.get("category") or "Общая медицина").strip(),
        "description": str(entry.get("description") or "").strip(),
        "symptoms": list(entry.get("symptoms") or []),
        "anamnesis_questions": _uniq(list(follow_up.get("must_ask") or []) + list(follow_up.get("optional") or []), 12),
        "red_flags": _uniq(list(triage.get("red_flags") or []), 12),
        "suggested_labs": _uniq(list(care.get("tests") or []), 8),
        "nutrition_recommendations": _uniq(list(care.get("nutrition") or []), 6),
        "physical_exercise_prevention_rehabilitation": _uniq(
            list(care.get("activity") or []) + list(care.get("prevention") or []),
            6,
        ),
        "common_user_phrasings": _uniq(list(entry.get("search_terms") or []), 12),
        "key_symptoms": list(entry.get("symptoms") or []),
        "must_ask_questions": _uniq(list(follow_up.get("must_ask") or []), 8),
        "optional_questions": _uniq(list(follow_up.get("optional") or []), 6),
        "red_flags_specific": _uniq(list(triage.get("red_flags") or []), 12),
        "likely_labs": _uniq(list(care.get("tests") or []), 8),
        "urgency_level": str(triage.get("recommended_care_level") or "").strip(),
        "likely_causes": _uniq(list(diag.get("possible_causes") or []), 8),
        "top_hypotheses": _uniq(list(diag.get("possible_causes") or []), 5),
        "first_line_non_drug_steps": _uniq(list(care.get("first_line") or []), 8),
        "medication_options_safe_general": _uniq(
            list(care.get("medications_safe_general") or []) + list(care.get("treatment") or []),
            8,
        ),
        "medication_options_doctor_only": _uniq(list(care.get("medications_doctor_only") or []), 8),
        "nutrition_advice": _uniq(list(care.get("nutrition") or []), 6),
        "physical_activity_advice": _uniq(list(care.get("activity") or []), 6),
        "prevention": _uniq(list(care.get("prevention") or []), 6),
        "what_makes_this_less_likely": _uniq(list(diag.get("what_makes_less_likely") or []), 6),
        "when_to_refer": _uniq(list(triage.get("red_flags") or []), 6),
        "expected_short_answer": "",
        "source": "medical_core_complaints",
        "dialogue_meta": {
            "ask_one_by_one": True,
            "wait_for_answer": bool(follow_up.get("wait_for_answer", True)),
            "analyze_and_follow_up": bool(follow_up.get("analyze_and_follow_up", True)),
            "pause_seconds_before_next": 2,
            "acknowledge_before_next": list(follow_up.get("acknowledge_before_next") or []),
        },
        "medical_core": entry,
    }


@lru_cache(maxsize=1)
def get_medical_core_complaints() -> list[dict[str, Any]]:
    repo = _repo()
    if repo is None:
        return []
    try:
        return [map_complaint_entry(x) for x in repo.catalog() if str(x.get("type") or "") == "complaint"]
    except Exception:
        return []


def search_medical_core(query: str, *, types: set[str] | None = None, limit: int = 6) -> list[dict[str, Any]]:
    engine = _engine()
    if engine is None:
        return []
    try:
        return engine.repo.search(query, types=types, limit=limit)
    except Exception:
        return []


def _best_complaint_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    complaints = [x for x in entries if str(x.get("type") or "") == "complaint"]
    if complaints:
        complaints.sort(
            key=lambda x: _care_level_rank(((x.get("triage") or {}).get("recommended_care_level") or "")),
            reverse=True,
        )
        return complaints[0]
    return entries[0] if entries else None


def build_medical_core_context(query: str) -> dict[str, Any]:
    rows = search_medical_core(query, limit=6)
    complaint_entry = _best_complaint_entry(rows)
    candidate_diseases: list[dict[str, Any]] = []
    behavior_rules: dict[str, Any] = {}
    summary: dict[str, Any] = {}
    if complaint_entry:
        engine = _engine()
        if engine is not None:
            try:
                plan = engine.complaint_plan(str(complaint_entry.get("entry_id") or ""))
                candidate_diseases = [x for x in (plan.get("candidate_diseases") or []) if isinstance(x, dict)]
                behavior_rules = dict(plan.get("behavior_rules") or {})
                summary = engine.safe_summary(str(complaint_entry.get("entry_id") or ""))
            except Exception:
                candidate_diseases = []
    if not summary and complaint_entry:
        triage = complaint_entry.get("triage") or {}
        care = complaint_entry.get("care") or {}
        summary = {
            "entry_id": complaint_entry.get("entry_id"),
            "name": complaint_entry.get("name"),
            "type": complaint_entry.get("type"),
            "care_level": triage.get("recommended_care_level") or "planned_consult",
            "red_flags": list(triage.get("red_flags") or [])[:5],
            "first_line": list(care.get("first_line") or [])[:5],
            "tests": list(care.get("tests") or [])[:3],
            "nutrition": list(care.get("nutrition") or [])[:3],
            "activity": list(care.get("activity") or [])[:3],
            "disclaimer": ((complaint_entry.get("policy") or {}).get("disclaimer_short") or ""),
        }
    return {
        "query": query,
        "hits": rows,
        "complaint_entry": complaint_entry,
        "complaint_protocol": map_complaint_entry(complaint_entry) if complaint_entry else None,
        "candidate_diseases": candidate_diseases,
        "safe_summary": summary,
        "behavior_rules": behavior_rules,
    }


def merge_structured_with_medical_core(structured: dict[str, Any] | None, context: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(structured or {})
    ctx = context or {}
    summary = ctx.get("safe_summary") or {}
    complaint_entry = ctx.get("complaint_entry") or {}
    candidate_diseases = [x for x in (ctx.get("candidate_diseases") or []) if isinstance(x, dict)]
    if not payload:
        payload = {}

    top_hypotheses = list(payload.get("top_hypotheses") or [])
    existing_names = {str((x or {}).get("name") or "").strip().lower() for x in top_hypotheses if isinstance(x, dict)}
    for idx, item in enumerate(candidate_diseases[:3]):
        name = str(item.get("name") or item.get("label") or "").strip()
        if not name or name.lower() in existing_names:
            continue
        why = []
        score = item.get("score")
        if score is not None:
            why.append(f"Matched via medical_core disease-linking (score {score}).")
        top_hypotheses.append({"name": name, "likelihood": "possible" if idx else "moderate", "why_it_fits": why})
        existing_names.add(name.lower())
    if not top_hypotheses and complaint_entry:
        name = str(complaint_entry.get("name") or "").strip()
        if name:
            top_hypotheses.append(
                {"name": name, "likelihood": "possible", "why_it_fits": [str(complaint_entry.get("description") or "").strip()]}
            )
    if top_hypotheses:
        payload["top_hypotheses"] = top_hypotheses[:5]

    def extend_unique(field: str, extra: list[str], limit: int) -> None:
        cur = [str(x).strip() for x in (payload.get(field) or []) if str(x).strip()]
        payload[field] = _uniq(cur + [str(x).strip() for x in extra if str(x).strip()], limit)

    extend_unique("recommended_labs", list(summary.get("tests") or []), 8)
    extend_unique("care_plan_today", list(summary.get("first_line") or []), 6)
    extend_unique("when_urgent", list(summary.get("red_flags") or []), 6)
    extend_unique("nutrition_advice", list(summary.get("nutrition") or []), 6)
    extend_unique("activity_advice", list(summary.get("activity") or []), 6)

    if not str(payload.get("patient_summary") or "").strip() and complaint_entry:
        payload["patient_summary"] = str(complaint_entry.get("description") or "").strip()
    if not str(payload.get("disclaimer") or "").strip() and summary.get("disclaimer"):
        payload["disclaimer"] = str(summary.get("disclaimer") or "").strip()

    payload["medical_core"] = {
        "matched_entry_id": summary.get("entry_id") or complaint_entry.get("entry_id"),
        "matched_name": summary.get("name") or complaint_entry.get("name"),
        "care_level": summary.get("care_level") or ((complaint_entry.get("triage") or {}).get("recommended_care_level") or ""),
        "candidate_diseases": [
            {"name": str(x.get("name") or x.get("label") or "").strip(), "score": x.get("score")}
            for x in candidate_diseases[:5]
            if str(x.get("name") or x.get("label") or "").strip()
        ],
        "behavior_rules": ctx.get("behavior_rules") or {},
    }
    return payload

