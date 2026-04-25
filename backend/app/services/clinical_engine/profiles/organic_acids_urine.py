"""
Профиль organic_acids_urine: не обрабатывается clinical_engine pipeline.
Обработка остаётся в существующем document_routes/organic_acids_route.
Этот модуль — заглушка для единой структуры profiles/.
"""
from __future__ import annotations

from typing import List

from app.services.clinical_engine.contracts import Finding, LabValue


def interpret_organic_acids_urine(values: List[LabValue]) -> List[Finding]:
    """Не используется в новом pipeline; organic acids обрабатываются старым движком."""
    return []
