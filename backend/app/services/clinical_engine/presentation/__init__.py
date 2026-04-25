"""
Политики подачи: один clinical core — разная глубина и стиль для врача и пациента.
"""
from app.services.clinical_engine.presentation.physician_style import PHYSICIAN_SECTION_TITLES
from app.services.clinical_engine.presentation.patient_safe_style import (
    patient_main_point_from_core,
    patient_finding_line,
    patient_next_step_line,
    patient_red_flags,
    patient_what_deviated_lines,
)

__all__ = [
    "PHYSICIAN_SECTION_TITLES",
    "patient_main_point_from_core",
    "patient_finding_line",
    "patient_next_step_line",
    "patient_red_flags",
    "patient_what_deviated_lines",
]
