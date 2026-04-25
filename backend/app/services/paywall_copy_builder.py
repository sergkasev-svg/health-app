"""
Тексты для paywall: спокойно, без агрессии и манипуляций.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.product_models import ProductOffer, UserEntitlements


def build_upgrade_prompt(
    feature_key: str,
    tier: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Один блок подсказки об апгрейде для фичи."""
    copy_map = {
        "physician_report": "Подробный отчёт для врача доступен в Pro.",
        "physician_report_text": "Подробный отчёт для врача доступен в Pro.",
        "lab_interpretation_advanced": "Расширенная интерпретация анализов доступна в Plus/Pro.",
        "trends_basic": "Сравнение анализов в динамике доступно в Plus.",
        "continuity_summary": "Сводка по сессии и тренды доступны в Plus.",
        "report_export": "Экспорт отчёта доступен в Pro.",
        "family_multi_profile": "Добавление профилей семьи доступно в тарифе Family.",
    }
    text = copy_map.get(feature_key, f"Функция доступна в расширенном тарифе.")
    return {
        "feature_key": feature_key,
        "tier": tier,
        "message": text,
        "cta": "Подробнее",
    }


def build_offer_cards(
    entitlements: UserEntitlements,
    context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Карточки офферов для показа пользователю (апгрейд, one-time)."""
    tier = (entitlements.tier or "free").lower()
    cards = []
    if tier == "free":
        cards.append({
            "offer_id": "plus",
            "title": "Плюс",
            "description": "Полный разбор анализов, память, динамика, follow-up.",
            "price": 299,
            "currency": "RUB",
            "cta": "Подробнее",
        })
        cards.append({
            "offer_id": "pro",
            "title": "Про",
            "description": "Отчёт для врача, экспорт, расширенные сценарии.",
            "price": 599,
            "currency": "RUB",
            "cta": "Подробнее",
        })
    elif tier == "plus":
        cards.append({
            "offer_id": "pro",
            "title": "Про",
            "description": "Отчёт для врача и экспорт.",
            "price": 599,
            "currency": "RUB",
            "cta": "Подробнее",
        })
    return cards
