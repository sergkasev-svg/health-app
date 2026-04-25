# -*- coding: utf-8 -*-
"""
Дифференциальный диагноз: структурированный список кандидатов с score и confidence.
"""
from __future__ import annotations

from typing import Any


def differential_diagnosis(
    ranked_diseases: list[tuple[int, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """
    Преобразует ranked_diseases (score, disease) в список с полями disease, score, confidence.
    """
    differential: list[dict[str, Any]] = []
    for score, disease in ranked_diseases or []:
        name = disease.get("name") or disease.get("id", "")
        confidence = min(1.0, score / 20.0) if score else 0.0
        differential.append({
            "disease": name,
            "score": score,
            "confidence": round(confidence, 2),
        })
    return differential
