from __future__ import annotations

from typing import Any


def build(
    *,
    case_state: dict[str, Any],
    care_level: str,
    hypotheses: list[dict[str, Any]] | None = None,
    red_flags: list[str] | None = None,
) -> dict[str, Any]:
    """Формирует политику рекомендаций по ветке и уровню помощи."""
    body_regions = set(case_state.get("body_regions", []) or [])
    active_branch = "general"
    if "oral_cavity" in body_regions:
        active_branch = "oral_cavity"
    elif "knee" in body_regions or "ankle" in body_regions or "back" in body_regions:
        active_branch = "orthopedics"

    policy = {
        "active_branch": active_branch,
        "allow_self_care": care_level in {"self_care_or_clarify", "planned_doctor_visit", "clarify"},
        "allow_supportive_advice": True,
        "allow_drug_details": False,
        "must_prioritize_urgency": care_level in {"emergency", "urgent_clinical_assessment"},
        "must_recommend_exam_if_red_flags": bool(red_flags),
        "max_questions": 3,
        "blocked_topics": [
            "unrelated_trauma_advice",
            "unrelated_cardiology_advice",
            "unrelated_cut_bleeding_advice",
        ],
    }

    if active_branch == "oral_cavity":
        policy["supportive_advice"] = [
            "не греть область боли",
            "по возможности не жевать на этой стороне",
            "поддерживать аккуратную гигиену полости рта",
        ]
    elif active_branch == "orthopedics":
        policy["supportive_advice"] = [
            "временно снизить нагрузку",
            "холод через ткань 15–20 минут",
            "не разрабатывать сустав через сильную боль",
        ]
    else:
        policy["supportive_advice"] = []

    return policy
