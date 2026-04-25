# -*- coding: utf-8 -*-
"""
Model Training Engine (V7): ретренировка/статистика по накопленным кейсам.
"""
from __future__ import annotations

import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2].parent
CASE_DB = _PROJECT_ROOT / "medical_learning" / "cases.json"


def retrain() -> dict[str, int]:
    """Возвращает статистику по подтверждённым диагнозам (disease -> count)."""
    if not CASE_DB.exists():
        return {}
    cases = json.loads(CASE_DB.read_text(encoding="utf-8"))
    stats: dict[str, int] = {}
    for c in cases:
        disease = c.get("confirmed_diagnosis") or ""
        if disease:
            stats.setdefault(disease, 0)
            stats[disease] += 1
    return stats
