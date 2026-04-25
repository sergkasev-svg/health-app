"""
Dual render: врач / пациент. Реализация: `renderers/physician_renderer`, `renderers/patient_safe_renderer`.
"""
from app.services.clinical_engine.renderers.patient_safe_renderer import render_patient_safe_report
from app.services.clinical_engine.renderers.physician_renderer import render_physician_report

__all__ = ["render_physician_report", "render_patient_safe_report"]
