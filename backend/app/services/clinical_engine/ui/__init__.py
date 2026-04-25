"""
UI routing и политики видимости. Реализация: `ui_routing.py`, `ui_policy/`.
"""
from app.services.clinical_engine.ui_policy.gating_policy import build_gated_payload
from app.services.clinical_engine.ui_policy.patient_policy import build_patient_payload
from app.services.clinical_engine.ui_policy.physician_policy import build_physician_payload
from app.services.clinical_engine.ui_routing import (
    get_gated_payload,
    get_patient_visible_payload,
    get_physician_visible_payload,
    route_core_to_ui,
)

__all__ = [
    "route_core_to_ui",
    "get_patient_visible_payload",
    "get_physician_visible_payload",
    "get_gated_payload",
    "build_patient_payload",
    "build_physician_payload",
    "build_gated_payload",
]
