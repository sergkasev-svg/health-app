# -*- coding: utf-8 -*-
"""
Confidence scoring: вероятность диагноза по совпадению симптомов с major/minor.
"""
from __future__ import annotations

from typing import Any


def calculate_confidence(symptom_ids: list[str], disease: dict[str, Any]) -> float:
    """
    symptom_ids — список id симптомов (из графа).
    disease — dict с major_symptoms, minor_symptoms.
    Возвращает 0.0 .. 1.0.
    """
    major = set(disease.get("major_symptoms") or [])
    minor = set(disease.get("minor_symptoms") or [])
    score = 0.0
    for s in symptom_ids or []:
        if s in major:
            score += 2.0
        elif s in minor:
            score += 1.0
    total = len(major) * 2 + len(minor)
    if total == 0:
        return 0.0
    return min(1.0, score / total)
