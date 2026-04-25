"""Логика монетизации: уровни доступа, ограничения по tier."""
from typing import Dict, Any


TIER_FEATURES = {
    "free": {
        "name": "Бесплатный",
        "features": {
            "analysis": True,
            "basic_response": True,
            "full_plan": False,
            "pdf_export": False,
            "recommendations": False,
            "dynamics": False,
            "repeat_analysis": False,
            "chat": False,
        },
    },
    "premium": {
        "name": "Премиум",
        "features": {
            "analysis": True,
            "basic_response": True,
            "full_plan": True,
            "pdf_export": True,
            "recommendations": True,
            "dynamics": False,
            "repeat_analysis": False,
            "chat": False,
        },
    },
    "subscription": {
        "name": "Подписка",
        "features": {
            "analysis": True,
            "basic_response": True,
            "full_plan": True,
            "pdf_export": True,
            "recommendations": True,
            "dynamics": True,
            "repeat_analysis": True,
            "chat": True,
        },
    },
}


def get_tier_features(tier: str) -> Dict[str, Any]:
    """Получить возможности для tier."""
    return TIER_FEATURES.get(tier, TIER_FEATURES["free"])


def can_access_feature(tier: str, feature: str) -> bool:
    """Проверка доступа к функции."""
    tier_data = get_tier_features(tier)
    return tier_data["features"].get(feature, False)


def get_upsell_message(tier: str) -> str:
    """Сообщение для upsell в зависимости от tier."""
    if tier == "free":
        return (
            "💡 Я вижу здесь не один показатель, а целую систему факторов.\n\n"
            "Могу собрать для вас полный персональный план:\n"
            "- что делать в первую очередь\n"
            "- как восстановить энергию\n"
            "- что убрать, чтобы не мешать восстановлению\n\n"
            "👉 Разблокировать полный план"
        )
    elif tier == "premium":
        return (
            "💡 Хотите отслеживать динамику и получать персональные рекомендации?\n\n"
            "👉 Оформить подписку"
        )
    return ""
