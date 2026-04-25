"""
Приведение LabValue к единому виду (единицы, ref) — заготовка для unified pipeline.
"""
from __future__ import annotations

from typing import Dict

from app.services.clinical_engine.contracts import LabValue


def normalize_values(values: Dict[str, LabValue]) -> Dict[str, LabValue]:
    """Пока pass-through; далее: конвертация единиц, дедуп кодов."""
    return dict(values)
