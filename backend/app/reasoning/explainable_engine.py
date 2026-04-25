# -*- coding: utf-8 -*-
"""
Explainable diagnosis: объяснение, почему симптом поддерживает диагноз (для врача).
"""
from __future__ import annotations

from typing import Any


def explain_diagnosis(
    disease: dict[str, Any],
    symptom_ids: list[str],
) -> list[str]:
    """
    По списку id симптомов и болезни возвращает список фраз-объяснений.
    """
    name = disease.get("name") or disease.get("id", "")
    major = set(disease.get("major_symptoms") or [])
    explanation: list[str] = []
    for sid in symptom_ids or []:
        if sid in major:
            explanation.append(f"Симптом «{sid}» характерен для {name}.")
    return explanation
