# -*- coding: utf-8 -*-
"""
Учёт лабораторных показателей в вероятности диагноза (lab_markers в описании болезни).
"""
from __future__ import annotations

from typing import Any


def lab_weight(labs: dict[str, Any], disease: dict[str, Any]) -> float:
    """
    labs: dict marker_key -> value (число).
    disease: dict с lab_markers = { "CRP": {"high": 10, "low": 0, "weight": 0.2}, ... }.
    Добавляет weight к оценке при value > high или value < low.
    """
    score = 0.0
    markers = disease.get("lab_markers") or {}
    if not isinstance(labs, dict):
        return score
    for marker_key, rule in markers.items():
        if not isinstance(rule, dict):
            continue
        high = rule.get("high", 999999)
        low = rule.get("low", -999999)
        weight = float(rule.get("weight", 0.2))
        val = labs.get(marker_key)
        if val is None:
            for k, v in labs.items():
                if (k or "").lower() == (marker_key or "").lower():
                    val = v
                    break
        if val is None:
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        if v > high:
            score += weight
        if v < low:
            score += weight
    return score
