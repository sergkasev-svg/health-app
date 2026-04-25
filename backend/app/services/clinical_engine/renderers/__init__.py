"""
Рендеры: один clinical core → physician report и patient-safe report.
"""
from app.services.clinical_engine.renderers.physician_renderer import render_physician_report
from app.services.clinical_engine.renderers.patient_safe_renderer import (
    patient_safe_report_to_example_json,
    render_patient_safe_html,
    render_patient_safe_report,
)

__all__ = [
    "render_physician_report",
    "render_patient_safe_report",
    "render_patient_safe_html",
    "patient_safe_report_to_example_json",
]
