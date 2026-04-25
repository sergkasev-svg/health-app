"""
Реестр кодов расчётных индексов и порядок вывода в отчёте врача.
"""
from __future__ import annotations

from typing import List

# Полный набор кодов (соответствует вычислителям в engine); порядок вывода — DERIVED_INDEX_ORDER
DERIVED_INDEX_REGISTRY_CODES: List[str] = [
    "bmi",
    "kerdo_vegetative_index",
    "iti",
    "nlr",
    "sii",
    "siri",
    "aisi",
    "harkavi_index",
    "iir",
]

# Порядок секции «Интегральные и расчётные индексы»
DERIVED_INDEX_ORDER: List[str] = [
    "bmi",
    "kerdo_vegetative_index",
    "iti",
    "nlr",
    "sii",
    "siri",
    "aisi",
    "harkavi_index",
    "iir",
]


def sort_derived_indices(indices: list) -> list:
    """Стабильная сортировка по DERIVED_INDEX_ORDER, неизвестные коды — в конце."""
    rank = {c: i for i, c in enumerate(DERIVED_INDEX_ORDER)}

    def key(x):
        return (rank.get(getattr(x, "code", ""), 999), getattr(x, "code", ""))

    return sorted(indices, key=key)
