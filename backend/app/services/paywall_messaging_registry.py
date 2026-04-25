"""
Честные upgrade-сообщения для paywall. Тон: спокойный, полезный, без давления и кликбейта.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.gtm_models import OfferMessage

# Ключ фичи -> сообщение (или несколько вариантов по placement)
PAYWALL_MESSAGES: Dict[str, list[Dict[str, Any]]] = {
    "physician_report": [
        {"message": "Можно открыть подробный отчёт для врача.", "placement": "teaser", "cta": "Подробнее"},
        {"message": "Подробный структурированный отчёт доступен в расширенном плане.", "placement": "gate", "cta": "Подробнее"},
    ],
    "physician_report_text": [
        {"message": "Отчёт для врача доступен в тарифе Про.", "placement": "gate", "cta": "Подробнее"},
    ],
    "continuity_summary": [
        {"message": "Сравнение анализов в динамике доступно в Plus.", "placement": "teaser", "cta": "Подробнее"},
        {"message": "Чтобы видеть изменения показателей со временем, можно включить расширенный план.", "placement": "gate", "cta": "Подробнее"},
    ],
    "trends_basic": [
        {"message": "Тренды и сравнение с прошлыми анализами доступны в Plus.", "placement": "teaser", "cta": "Подробнее"},
    ],
    "family_multi_profile": [
        {"message": "Несколько профилей доступны в тарифе Семья.", "placement": "gate", "cta": "Подробнее"},
    ],
    "lab_interpretation_advanced": [
        {"message": "Разбор нескольких документов и расширенная интерпретация доступны в Pro.", "placement": "gate", "cta": "Подробнее"},
    ],
    "report_export": [
        {"message": "Экспорт отчёта в PDF доступен в Pro.", "placement": "gate", "cta": "Подробнее"},
    ],
}


def get_paywall_message(
    feature_key: str,
    placement: str = "gate",
    tier: str = "free",
) -> Optional[Dict[str, Any]]:
    """Возвращает одно сообщение для фичи и placement. Без небезопасных формулировок."""
    options = PAYWALL_MESSAGES.get(feature_key) or PAYWALL_MESSAGES.get("physician_report")
    if not options:
        return {"message": "Функция доступна в расширенном тарифе.", "placement": placement, "cta": "Подробнее"}
    for o in options:
        if o.get("placement") == placement:
            return {"feature_key": feature_key, "tier": tier, **o}
    fallback = options[0]
    return {"feature_key": feature_key, "tier": tier, "message": fallback.get("message"), "placement": placement, "cta": fallback.get("cta", "Подробнее")}


def get_all_paywall_offer_messages() -> list[OfferMessage]:
    out = []
    for feature_key, opts in PAYWALL_MESSAGES.items():
        for o in opts:
            out.append(OfferMessage(
                offer_id=feature_key,
                title="",
                body=o.get("message", ""),
                cta=o.get("cta", "Подробнее"),
                placement=o.get("placement", "gate"),
                audience=["b2c_general", "engaged_health"],
            ))
    return out
