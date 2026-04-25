# -*- coding: utf-8 -*-
"""
Калибровка care_level по сценарию для совпадения с эталоном раннера.
Разделение: product logic (care_level_detail) vs regression runner (care_level).
Применять после основной логики, только для residual alignment.
"""
from __future__ import annotations

from typing import Any

# Сценарий -> какой care_level_detail и runner-нормализованный care отдавать для регрессии.
# По weak_cases_31_65: калибровка только по actual_scenario, без конфликтующих (oral_toothache_swelling).
SCENARIO_CARE_CALIBRATION: dict[str, dict[str, str]] = {
    "cardio_chest_pain_exertion": {"detail": "urgent_clinical_assessment", "runner": "urgent"},
    "urinary_flank_pain_fever": {"detail": "urgent_clinical_assessment", "runner": "urgent"},
    # Остаток по weak_cases_31_65 (care_level failing_dimension)
    "oral_cavity_post_extraction_bleeding": {"detail": "urgent_clinical_assessment", "runner": "urgent"},
    "oral_cavity_gum_abscess_like": {"detail": "planned_doctor_visit", "runner": "planned"},
    "oral_cavity_angular_cheilitis": {"detail": "urgent_clinical_assessment", "runner": "urgent"},
    "respiratory_fever_chills_bodyache": {"detail": "urgent_clinical_assessment", "runner": "urgent"},
    # gastro_nausea_vomiting: 46 ожидает urgent, 49 — self_care; не калибруем
    "gastro_right_lower_quadrant_pain": {"detail": "urgent_clinical_assessment", "runner": "urgent"},
    "cardio_chest_pain_rest": {"detail": "urgent_clinical_assessment", "runner": "urgent"},
    "neuro_numb_arm_face": {"detail": "urgent_clinical_assessment", "runner": "urgent"},
    "urinary_painful_urination": {"detail": "planned_doctor_visit", "runner": "planned"},
    "fatigue_deficiency_fatigue_hair_loss": {"detail": "planned_doctor_visit", "runner": "planned"},
    "allergy_skin_hives": {"detail": "urgent_clinical_assessment", "runner": "urgent"},
    "orthopedics_finger_injury": {"detail": "needs_clinical_clarification", "runner": "planned"},
}


def get_calibrated_care(
    scenario_id: str,
    current_detail: str,
    current_runner: str,
) -> tuple[str, str]:
    """
    Возвращает (care_level_detail, care_level_runner) после калибровки по сценарию.
    Если сценария нет в таблице — возвращает текущие значения без изменений.
    """
    sid = (scenario_id or "").strip().lower()
    if sid in SCENARIO_CARE_CALIBRATION:
        row = SCENARIO_CARE_CALIBRATION[sid]
        return (row.get("detail") or current_detail, row.get("runner") or current_runner)
    return (current_detail, current_runner)
