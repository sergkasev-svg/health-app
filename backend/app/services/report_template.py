"""
Унифицированный шаблон отчёта (совместимость с именем из методички).

Используйте `gold_standard_report.build_gold_standard_bundle` для полной структуры секций.
"""
from __future__ import annotations

from app.services.gold_standard_report import (
    LEGAL_DISCLAIMER_SHORT,
    REFINEMENT_GENERIC,
    build_gold_standard_bundle,
    build_gold_standard_for_aggregate,
    merge_gold_into_user_structured,
)

__all__ = [
    "LEGAL_DISCLAIMER_SHORT",
    "REFINEMENT_GENERIC",
    "build_gold_standard_bundle",
    "build_gold_standard_for_aggregate",
    "merge_gold_into_user_structured",
]
