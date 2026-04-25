# -*- coding: utf-8 -*-
"""
Интерпретация лабораторных показателей для триажа и диагностического графа.
"""
from __future__ import annotations

from typing import Any


def analyze_labs(document_text: str) -> dict[str, Any]:
    """
    Анализ текста (документ/контекст) на предмет лабораторных данных.
    Возвращает dict с ключами suggested_tests, signals и т.д. для консультации.
    """
    result: dict[str, Any] = {"suggested_tests": [], "signals": []}
    if not (document_text or "").strip():
        return result
    # При необходимости можно парсить текст и вызывать interpret_labs
    return result


def interpret_labs(labs: dict[str, Any] | list[Any]) -> list[str]:
    """
    Принимает labs как dict (analyte_id -> value) или list[ParsedLabValue-like].
    Возвращает список сигналов: inflammation, infection, anemia и т.д.
    """
    results: list[str] = []
    if isinstance(labs, list):
        by_id: dict[str, float] = {}
        for item in labs:
            if hasattr(item, "analyte_id"):
                aid = getattr(item, "analyte_id", None) or (item.get("analyte_id") if isinstance(item, dict) else None)
                val = getattr(item, "value", None) if hasattr(item, "value") else (item.get("value") if isinstance(item, dict) else None)
                if aid is not None and val is not None:
                    try:
                        by_id[str(aid).lower()] = float(val)
                    except (TypeError, ValueError):
                        pass
        labs = by_id
    if not isinstance(labs, dict):
        return results
    for k, v in labs.items():
        try:
            val = float(v)
        except (TypeError, ValueError):
            continue
        k_low = str(k).lower()
        if "crp" in k_low or k_low == "c-reactive":
            if val > 10:
                results.append("inflammation")
        if "wbc" in k_low or "лейкоцит" in k_low or k_low == "leukocytes":
            if val > 11:
                results.append("infection")
        if "hemoglobin" in k_low or "hgb" in k_low or "гемоглобин" in k_low:
            if val < 110:
                results.append("anemia")
        if "ferritin" in k_low or "ферритин" in k_low:
            if val < 15:
                results.append("anemia")
    return list(dict.fromkeys(results))
