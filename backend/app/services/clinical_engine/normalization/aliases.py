"""
Канонические коды маркеров и алиасы из текста (слой нормализации).
Постепенно переносить сюда правила из extractors / lab_knowledge.
"""
from __future__ import annotations

from typing import Dict

# Пример карты (расширять по мере миграции)
MARKER_ALIASES: Dict[str, str] = {
    "гемоглобин": "hb",
    "эритроциты": "rbc",
    "лейкоциты": "wbc",
    "тромбоциты": "plt",
    "холестерин общий": "total_cholesterol",
    "холестерин-лпнп": "ldl_cholesterol",
    "холестерин-лпвп": "hdl_cholesterol",
    "фруктозамин": "fructosamine",
    "гликированный гемоглобин": "hba1c",
    "реакция на кровь": "urine_blood",
    "лейкоциты мочи": "urine_leukocytes",
}


def resolve_alias(raw_label: str) -> str:
    """Возвращает канонический ключ или lower(raw) если не найден."""
    low = (raw_label or "").strip().lower()
    return MARKER_ALIASES.get(low, low.replace(" ", "_"))
