"""
Контракт material-first маршрутизации: биоматериал → допустимые профили → report_type.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class MaterialKind(str, Enum):
    """Первичный слой: из чего взят образец."""

    BLOOD = "blood"
    URINE = "urine"
    STOOL = "stool"
    SALIVA = "saliva"
    SWAB = "swab"  # мазок слизистой / урогенитал / ЛОР
    CSF = "csf"  # ликвор
    SEMEN = "semen"
    TISSUE = "tissue"  # биопсия / гистология
    SERUMLOGY = "serology"  # серология
    GENETICS = "genetics"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"  # противоречивые сигналы; нужен ручной выбор


class MaterialRoutingResult(BaseModel):
    """Результат: материал + итоговый тип отчёта + метаданные для аудита."""

    material: MaterialKind = MaterialKind.UNKNOWN
    material_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    report_type: str = "unknown"  # совместимо с document_type_detector.ReportType
    blood_subprofile: Optional[str] = None  # cbc | lipid | biochemistry | ...
    reasons: List[str] = Field(default_factory=list)
    allowed_profiles: List[str] = Field(default_factory=list)
    forbidden_profiles: List[str] = Field(default_factory=list)
    cbc_override: bool = False  # жёсткий приоритет ОАК над другими blood-профилями
    conflict_note: Optional[str] = None
