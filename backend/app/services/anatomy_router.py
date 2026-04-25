# -*- coding: utf-8 -*-
"""
Анатомический роутинг для ортопедии: выбор зоны (ankle, shoulder, low_back, knee) по тексту.
Используется в scenario_router для выбора правильного ортопедического сценария (fix 32–34).
"""
from __future__ import annotations

ORTHO_ZONES: dict[str, list[str]] = {
    "ankle": [
        "голеностоп",
        "лодыжк",
        "щиколотк",
        "подвернул ногу",
        "травма голеностопа",
    ],
    "knee": [
        "колено",
        "колен",
    ],
    "finger": [
        "палец",
        "фаланга",
        "пальца",
    ],
    "shoulder": [
        "плечо",
        "плечевой",
        "нестабильность плеча",
    ],
    "rib": [
        "ребро",
        "рёбра",
        "бок болит при вдохе",
    ],
    "low_back": [
        "поясниц",
        "прострел",
        "отдаёт в ногу",
        "отдает в ногу",
        "седалищ",
        "сорвал спину",
        "спину сорвал",
    ],
}


def detect_ortho_zone(text: str) -> str | None:
    """Определяет ортопедическую зону по тексту. Порядок проверки важен: более специфичные фразы первыми."""
    t = (text or "").lower().replace("ё", "е")
    for zone, words in ORTHO_ZONES.items():
        for w in words:
            if w in t:
                return zone
    return None


# Совместимость с Production V3 (ANATOMY / detect_anatomy)
ANATOMY = ORTHO_ZONES


def detect_anatomy(text: str) -> str | None:
    """Алиас для detect_ortho_zone."""
    return detect_ortho_zone(text)
