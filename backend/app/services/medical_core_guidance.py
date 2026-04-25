from __future__ import annotations

from typing import Any


_SPECIALIST_MAP = {
    "cardio": "Кардиолог",
    "neuro": "Невролог",
    "gi": "Гастроэнтеролог",
    "resp": "Пульмонолог/терапевт",
    "skin": "Дерматолог",
    "uro": "Уролог",
    "gyne": "Гинеколог",
    "msk": "Травматолог-ортопед",
    "ent": "ЛОР",
    "endo": "Эндокринолог",
    "general": "Терапевт",
}

_TRIAGE_LABELS = {
    "self_care": "Самопомощь",
    "planned_consult": "Плановая консультация",
    "same_day": "Осмотр сегодня",
    "urgent": "Срочная помощь",
    "emergency": "Неотложная помощь",
    "emergency_ambulance": "Вызов скорой",
}

_TRIAGE_TARGETS = {
    "self_care": "Наблюдение дома с контрольной оценкой",
    "planned_consult": "Запись к врачу в плановом порядке",
    "same_day": "Очный осмотр в этот же день",
    "urgent": "Срочное обращение за медицинской помощью",
    "emergency": "Обратиться в неотложную помощь немедленно",
    "emergency_ambulance": "Вызвать 103/112 немедленно",
}


def _uniq(items: list[str], limit: int | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        s = str(item or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if limit is not None and len(out) >= limit:
            break
    return out


def _clean_strings(items: list[Any], limit: int | None = None) -> list[str]:
    return _uniq([str(x).strip() for x in (items or []) if str(x).strip()], limit)


def _care_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {}
    care = entry.get("care")
    if isinstance(care, dict):
        return care
    # mapped complaint_protocol-style structure
    return {
        "first_line": list(entry.get("first_line_non_drug_steps") or []),
        "medications_safe_general": list(entry.get("medication_options_safe_general") or []),
        "medications_doctor_only": list(entry.get("medication_options_doctor_only") or []),
        "nutrition": list(entry.get("nutrition_advice") or []),
        "activity": list(entry.get("physical_activity_advice") or []),
        "prevention": list(entry.get("prevention") or []),
        "tests": list(entry.get("likely_labs") or []),
        "treatment": list(entry.get("medication_options_safe_general") or []),
    }


def _follow_up_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {}
    fu = entry.get("follow_up")
    if isinstance(fu, dict):
        return fu
    return {
        "must_ask": list(entry.get("must_ask_questions") or []),
        "optional": list(entry.get("optional_questions") or []),
    }


def _triage_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {}
    tr = entry.get("triage")
    if isinstance(tr, dict):
        return tr
    return {
        "recommended_care_level": str(entry.get("urgency_level") or "").strip(),
        "red_flags": list(entry.get("red_flags_specific") or entry.get("red_flags") or []),
    }


def _route_specialist(complaint_entry: dict[str, Any] | None) -> str:
    row = complaint_entry or {}
    domain = str(row.get("domain") or "").strip().lower()
    if domain in _SPECIALIST_MAP:
        return _SPECIALIST_MAP[domain]
    category = str(row.get("category") or "").strip().lower()
    if "серд" in category or "давлен" in category:
        return "Кардиолог"
    if "невро" in category or "голов" in category:
        return "Невролог"
    if "кожа" in category:
        return "Дерматолог"
    if "лор" in category or "ухо" in category or "горл" in category or "нос" in category:
        return "ЛОР"
    if "желуд" in category or "киш" in category or "жкт" in category:
        return "Гастроэнтеролог"
    return "Терапевт"


def _choose_question(payload: dict[str, Any], complaint_entry: dict[str, Any] | None) -> list[str]:
    existing = _clean_strings(list(payload.get("follow_up_questions") or []), 1)
    if existing:
        return existing
    row = complaint_entry or {}
    follow_up = _follow_up_from_entry(row)
    red_flag_questions = _clean_strings(list(follow_up.get("red_flag_questions") or []), 2)
    must_ask = _clean_strings(list(follow_up.get("must_ask") or []), 8)
    if not payload.get("red_flags_present") and red_flag_questions:
        return red_flag_questions[:1]
    if must_ask:
        return must_ask[:1]
    return []


def _build_treatment_plan(payload: dict[str, Any], complaint_entry: dict[str, Any] | None, summary: dict[str, Any]) -> dict[str, Any]:
    row = complaint_entry or {}
    care = _care_from_entry(row)
    first_line = _clean_strings(
        list(payload.get("care_plan_today") or [])
        + list(summary.get("first_line") or [])
        + list(care.get("first_line") or []),
        6,
    )
    medications_safe = _clean_strings(
        list(care.get("medications_safe_general") or []) + list(care.get("treatment") or []),
        6,
    )
    medications_doctor_only = _clean_strings(list(care.get("medications_doctor_only") or []), 5)
    nutrition = _clean_strings(
        list(payload.get("nutrition_advice") or [])
        + list(summary.get("nutrition") or [])
        + list(care.get("nutrition") or []),
        6,
    )
    activity = _clean_strings(
        list(payload.get("activity_advice") or [])
        + list(summary.get("activity") or [])
        + list(care.get("activity") or []),
        6,
    )
    prevention = _clean_strings(list(care.get("prevention") or []), 6)

    triage_level = str(summary.get("care_level") or "").strip().lower()
    what_not_to_do: list[str] = []
    if triage_level in {"same_day", "urgent", "emergency", "emergency_ambulance"}:
        what_not_to_do.append("Не откладывайте очную помощь при ухудшении состояния.")
    if medications_doctor_only:
        what_not_to_do.append("Не начинайте рецептурные препараты без назначения врача.")
    if str(row.get("domain") or "").strip().lower() in {"cardio", "resp"}:
        what_not_to_do.append("Избегайте интенсивной физической нагрузки до стабилизации симптомов.")

    return {
        "what_to_do": first_line,
        "what_not_to_do": _uniq(what_not_to_do, 4),
        "medications_safe_general": medications_safe,
        "medications_doctor_only": medications_doctor_only,
        "nutrition": nutrition,
        "activity": activity,
        "prevention": prevention,
    }


def _has_guidance_context(context: dict[str, Any]) -> bool:
    if not isinstance(context, dict):
        return False
    if isinstance(context.get("complaint_entry"), dict) and context.get("complaint_entry"):
        return True
    if isinstance(context.get("safe_summary"), dict) and context.get("safe_summary"):
        return True
    return bool(context.get("candidate_diseases"))


def apply_medical_core_guidance(
    structured: dict[str, Any] | None,
    context: dict[str, Any] | None,
    *,
    user_message: str = "",
) -> dict[str, Any]:
    payload = dict(structured or {})
    ctx = context or {}
    if not payload or not _has_guidance_context(ctx):
        return payload

    complaint_entry = ctx.get("complaint_entry") or {}
    summary = dict(ctx.get("safe_summary") or {})
    if not summary:
        triage = _triage_from_entry(complaint_entry)
        care = _care_from_entry(complaint_entry)
        summary = {
            "care_level": str(triage.get("recommended_care_level") or "").strip() or "planned_consult",
            "red_flags": _clean_strings(list(triage.get("red_flags") or []), 8),
            "tests": _clean_strings(list(care.get("tests") or []), 6),
            "first_line": _clean_strings(list(care.get("first_line") or []), 6),
            "nutrition": _clean_strings(list(care.get("nutrition") or []), 6),
            "activity": _clean_strings(list(care.get("activity") or []), 6),
        }

    triage_id = str(summary.get("care_level") or "planned_consult").strip().lower() or "planned_consult"
    triage_label = _TRIAGE_LABELS.get(triage_id, triage_id)
    triage_target = _TRIAGE_TARGETS.get(triage_id, "")
    specialist = _route_specialist(complaint_entry)

    questions = _choose_question(payload, complaint_entry)
    if questions:
        payload["follow_up_questions"] = questions[:1]
        payload["missing_information"] = _uniq(list(payload.get("missing_information") or []) + questions, 3)

    recommended_labs = _clean_strings(list(payload.get("recommended_labs") or []) + list(summary.get("tests") or []), 5)
    if triage_id in {"self_care", "planned_consult"}:
        recommended_labs = recommended_labs[:3]
    if recommended_labs:
        payload["recommended_labs"] = recommended_labs

    hypotheses = list(payload.get("top_hypotheses") or [])
    seen = {str((x or {}).get("name") or "").strip().lower() for x in hypotheses if isinstance(x, dict)}
    for idx, item in enumerate(ctx.get("candidate_diseases") or []):
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("label") or "").strip()
            score = item.get("score")
            why_matches = [str(x).strip() for x in (item.get("why_matches") or []) if str(x).strip()]
        else:
            name = str(item or "").strip()
            score = None
            why_matches = []
        if not name or name.lower() in seen:
            continue
        if not why_matches and score is not None:
            why_matches = [f"Совпадение по medical_core (score {score})."]
        hypotheses.append(
            {
                "name": name,
                "likelihood": "possible" if idx else "moderate",
                "why_it_fits": why_matches[:3],
            }
        )
        seen.add(name.lower())
        if len(hypotheses) >= 5:
            break
    if hypotheses:
        payload["top_hypotheses"] = hypotheses[:5]

    treatment = _build_treatment_plan(payload, complaint_entry, summary)
    payload["care_plan_today"] = _clean_strings(list(payload.get("care_plan_today") or []) + treatment.get("what_to_do", []), 6)
    payload["nutrition_advice"] = treatment.get("nutrition") or list(payload.get("nutrition_advice") or [])
    payload["activity_advice"] = treatment.get("activity") or list(payload.get("activity_advice") or [])
    payload["treatment_plan"] = treatment

    when_urgent = _clean_strings(list(payload.get("when_urgent") or []) + list(summary.get("red_flags") or []), 6)
    if when_urgent:
        payload["when_urgent"] = when_urgent

    payload["clinical_guidance"] = {
        "triage_level": triage_id,
        "triage_label": triage_label,
        "triage_target": triage_target,
        "specialist_route": specialist,
        "one_question_per_turn": True,
        "hypothesis_only": True,
        "safety_netting": "При ухудшении состояния или появлении красных флагов обратитесь за очной помощью.",
    }

    payload["medical_core"] = dict(payload.get("medical_core") or {})
    payload["medical_core"]["best_question"] = questions[:1]
    payload["medical_core"]["specialist_route"] = specialist
    payload["medical_core"]["triage_label"] = triage_label
    payload["medical_core"]["triage_target"] = triage_target

    if not payload.get("specialist_route"):
        payload["specialist_route"] = specialist

    # Keep plain hypotheses list for existing UI clients.
    if payload.get("top_hypotheses"):
        hyp_names = [str((x or {}).get("name") or "").strip() for x in payload["top_hypotheses"] if isinstance(x, dict)]
        hyp_names = [x for x in hyp_names if x]
        if hyp_names:
            payload["hypotheses"] = _uniq(list(payload.get("hypotheses") or []) + hyp_names, 5)

    if user_message and not payload.get("patient_summary"):
        payload["patient_summary"] = f"Запрос пользователя: {user_message[:240]}"
    return payload

