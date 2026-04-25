"""
Определение типа лабораторного документа.
Критично для изоляции логики: organic acids → только метаболика, без инфекций/аллергий.
"""
from __future__ import annotations


def detect_lab_type(text: str) -> str:
    """
    Определяет тип лабораторного документа по тексту.
    Возвращает: organic_acids, cbc, thyroid, unknown.
    """
    t = (text or "").lower()

    if "органических кислот" in t or "гх-мс" in t or "organic_acids" in t:
        return "organic_acids"

    if "гемоглобин" in t and "лейкоциты" in t:
        return "cbc"

    if "ттг" in t or "tsh" in t or "тиреотроп" in t:
        return "thyroid"

    return "unknown"
