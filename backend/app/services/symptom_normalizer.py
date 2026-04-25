# -*- coding: utf-8 -*-
"""
Нормализация формулировок симптомов для единообразного сопоставления с графом и триажем.
"""
from __future__ import annotations

NORMALIZATION: dict[str, str] = {
    "болит": "боль",
    "ломит": "боль",
    "тянет": "боль",
    "жар": "температура",
    "лихорадка": "температура",
    "рези": "жжение",
    "саднит": "боль",
    "ноет": "боль",
}


def normalize(text: str) -> str:
    """Приводит текст к нормализованным формулировкам симптомов."""
    if not text:
        return ""
    t = text.lower().replace("ё", "е")
    for k, v in NORMALIZATION.items():
        t = t.replace(k, v)
    return t.strip()
