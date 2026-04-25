"""
Material-first слой: биоматериал → допустимые профили → report_type.

См. README.md в этой папке — краткая методичка для промптов и разработки.
"""
from app.services.clinical_engine.material_protocols.contract import MaterialKind, MaterialRoutingResult
from app.services.clinical_engine.material_protocols.material_router import (
    report_type_to_document_type,
    route_blood_profile,
    route_document,
)
from app.services.clinical_engine.material_protocols.registry import MATERIAL_ALLOWED_PROFILES, MATERIAL_FORBIDDEN_CROSS

__all__ = [
    "MaterialKind",
    "MaterialRoutingResult",
    "route_document",
    "route_blood_profile",
    "report_type_to_document_type",
    "MATERIAL_ALLOWED_PROFILES",
    "MATERIAL_FORBIDDEN_CROSS",
]
