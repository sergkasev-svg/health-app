"""
UI-level policies: что показывать пациенту, врачу, что скрывать за gating.
Routing не меняет клинический смысл — только видимость и подача.
"""
from app.services.clinical_engine.ui_policy.patient_policy import build_patient_payload
from app.services.clinical_engine.ui_policy.physician_policy import build_physician_payload
from app.services.clinical_engine.ui_policy.gating_policy import build_gated_payload

__all__ = ["build_patient_payload", "build_physician_payload", "build_gated_payload"]
