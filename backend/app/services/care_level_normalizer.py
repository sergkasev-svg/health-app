# -*- coding: utf-8 -*-
"""
Нормализация care_level к формату, ожидаемому регрессией и UI:
urgent_clinical_assessment | planned_doctor_visit | self_care_or_clarify | needs_clinical_clarification
"""
from __future__ import annotations

CARE_LEVEL_MAP: dict[str, str] = {
    "emergency": "urgent_clinical_assessment",
    "er": "urgent_clinical_assessment",
    "same_day": "urgent_clinical_assessment",
    "urgent_eval": "urgent_clinical_assessment",
    "urgent_review": "urgent_clinical_assessment",
    "urgent_visit": "urgent_clinical_assessment",
    "urgent_clinical_assessment": "urgent_clinical_assessment",
    "urgent": "urgent_clinical_assessment",
    "urgent_clinical": "urgent_clinical_assessment",
    "doctor_visit": "planned_doctor_visit",
    "clinic_visit": "planned_doctor_visit",
    "scheduled_visit": "planned_doctor_visit",
    "planned_doctor_visit": "planned_doctor_visit",
    "planned": "planned_doctor_visit",
    "home_care": "self_care_or_clarify",
    "observe": "self_care_or_clarify",
    "supportive_care": "self_care_or_clarify",
    "self_care": "self_care_or_clarify",
    "self_care_or_clarify": "self_care_or_clarify",
    "self_care_watchful_waiting": "self_care_or_clarify",
    "clarify": "needs_clinical_clarification",
    "needs_clinical_clarification": "needs_clinical_clarification",
    "needs_more_data": "needs_clinical_clarification",
}


def normalize_care_level(value: str | None) -> str:
    """Приводит значение care_level к одному из стандартных."""
    if not value or not str(value).strip():
        return "needs_clinical_clarification"
    key = str(value).lower().strip()
    return CARE_LEVEL_MAP.get(key, "needs_clinical_clarification")
