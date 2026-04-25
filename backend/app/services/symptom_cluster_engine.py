# -*- coding: utf-8 -*-
"""
Кластеризация симптомов для приоритетного triage.
Системные признаки (температура + почки/мочевые) → urinary до ортопедии (fix case 58).
"""
from __future__ import annotations

SYSTEMIC_SIGNS = [
    "температур",
    "лихорад",
    "озноб",
]

URINARY_SIGNS = [
    "мочеиспуск",
    "писать",
    "жжение",
    "рези",
    "часто хожу",
    "частое мочеиспуск",
    "больно писать",
]

KIDNEY_PAIN = [
    "поясниц",
    "бок",
    "почка",
    "в боку",
    "ломит",
]

ORTHO_SIGNS = [
    "подвернул",
    "удар",
    "потянул",
    "травма",
]


def detect_clusters(text: str) -> dict[str, bool]:
    """Определяет наличие кластеров симптомов в тексте."""
    t = (text or "").lower().replace("ё", "е")
    return {
        "systemic": any(x in t for x in SYSTEMIC_SIGNS),
        "urinary": any(x in t for x in URINARY_SIGNS),
        "kidney": any(x in t for x in KIDNEY_PAIN),
        "orthopedic": any(x in t for x in ORTHO_SIGNS),
    }


def priority_triage(text: str) -> str | None:
    """
    Приоритетный маршрут: при системной инфекции + почки/мочевые → urinary.
    Вызывать до обычного detect_branch, чтобы кейс 58 (поясница + температура) шёл в urinary.
    """
    clusters = detect_clusters(text)
    if clusters["systemic"] and clusters["kidney"]:
        return "urinary"
    if clusters["systemic"] and clusters["urinary"]:
        return "urinary"
    return None
