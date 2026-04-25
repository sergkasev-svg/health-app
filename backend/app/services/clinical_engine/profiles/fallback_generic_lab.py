"""
Профиль generic_lab: минимальный отчёт без ложного fallback.
При ≥3 валидных показателя запрещено писать «нет значимых отклонений».
"""
from __future__ import annotations

from typing import List

from app.services.clinical_engine.contracts import Finding, LabValue


def interpret_fallback_generic(values: List[LabValue]) -> List[Finding]:
    """Для generic_lab_document при недостатке данных для профиля — пустой список findings."""
    return []
