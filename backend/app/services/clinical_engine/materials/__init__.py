"""
Слой биоматериала (material-first). Реализация: см. `material_protocols/`.

Целевая схема: material → allowed_profiles → profile router.
"""
from app.services.clinical_engine.material_protocols import (
    MATERIAL_ALLOWED_PROFILES,
    MATERIAL_FORBIDDEN_CROSS,
    MaterialKind,
    MaterialRoutingResult,
    route_document,
    route_blood_profile,
    report_type_to_document_type,
)
__all__ = [
    "MaterialKind",
    "MaterialRoutingResult",
    "route_document",
    "route_blood_profile",
    "report_type_to_document_type",
    "MATERIAL_ALLOWED_PROFILES",
    "MATERIAL_FORBIDDEN_CROSS",
]
