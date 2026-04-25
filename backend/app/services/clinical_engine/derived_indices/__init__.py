"""
Слой расчётных интегральных индексов (ИМТ, Кердо, ИТИ, NLR/SII/SIRI/AISI, Гаркави, ИИР).

Подключается после извлечения LabValue и не заменяет существующую интерпретацию профиля.
"""
from app.services.clinical_engine.derived_indices.contract import DerivedIndex
from app.services.clinical_engine.derived_indices.engine import (
    compute_derived_indices_for_document,
    format_derived_indices_section,
)
from app.services.clinical_engine.derived_indices.registry import DERIVED_INDEX_ORDER, sort_derived_indices

__all__ = [
    "DerivedIndex",
    "DERIVED_INDEX_ORDER",
    "compute_derived_indices_for_document",
    "format_derived_indices_section",
    "sort_derived_indices",
]
