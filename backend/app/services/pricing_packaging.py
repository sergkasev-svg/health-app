"""
Launch-ready тарифы: FREE, PLUS, PRO, FAMILY, CLINIC.
Placeholder pricing; реальные цены задаются в конфиге/биллинге.
"""
from __future__ import annotations

from app.services.gtm_models import PricingTierCard


# Место для реальных цен: env или billing config. Сейчас placeholder.
PRICING_PLACEHOLDER = {
    "plus_monthly": None,   # 299
    "plus_yearly": None,    # 2990
    "pro_monthly": None,    # 599
    "pro_yearly": None,     # 5990
    "family_monthly": None, # 799
    "family_yearly": None,  # 7990
    "currency": "RUB",
}


def get_pricing_tier_cards(currency: str | None = None) -> list[PricingTierCard]:
    curr = currency or PRICING_PLACEHOLDER.get("currency") or "RUB"
    return [
        PricingTierCard(
            tier_id="free",
            title="Бесплатный",
            subtitle="Вход в продукт и первая ценность",
            monthly_price=0.0,
            yearly_price=0.0,
            currency=curr,
            bullet_points=[
                "Базовый чат по симптомам",
                "Экстренная триажа",
                "Ограниченный разбор анализов",
                "Короткий план действий",
                "Ограниченная память / история",
            ],
            recommended=False,
            cta="Начать бесплатно",
            target_audience=["b2c_general"],
        ),
        PricingTierCard(
            tier_id="plus",
            title="Плюс",
            subtitle="Основной массовый тариф",
            monthly_price=PRICING_PLACEHOLDER.get("plus_monthly") or 299.0,
            yearly_price=PRICING_PLACEHOLDER.get("plus_yearly") or 2990.0,
            currency=curr,
            bullet_points=[
                "Расширенный разбор анализов",
                "Сводка continuity",
                "Follow-up и тренды",
                "Больше загрузок и разборов",
                "Расширенные планы действий",
            ],
            recommended=True,
            cta="Подробнее",
            target_audience=["b2c_general", "engaged_health"],
        ),
        PricingTierCard(
            tier_id="pro",
            title="Про",
            subtitle="Для активных пользователей и сложных кейсов",
            monthly_price=PRICING_PLACEHOLDER.get("pro_monthly") or 599.0,
            yearly_price=PRICING_PLACEHOLDER.get("pro_yearly") or 5990.0,
            currency=curr,
            bullet_points=[
                "Отчёт для врача (physician report)",
                "Многофайловый анализ",
                "Экспорт отчётов",
                "Более глубокая интерпретация",
                "Расширенная история",
            ],
            recommended=False,
            cta="Подробнее",
            target_audience=["engaged_health", "b2c_general"],
        ),
        PricingTierCard(
            tier_id="family",
            title="Семья",
            subtitle="Несколько профилей, забота о близких",
            monthly_price=PRICING_PLACEHOLDER.get("family_monthly") or 799.0,
            yearly_price=PRICING_PLACEHOLDER.get("family_yearly") or 7990.0,
            currency=curr,
            bullet_points=[
                "Несколько профилей",
                "Семейное сопровождение",
                "Общие отчёты и follow-up",
            ],
            recommended=False,
            cta="Подробнее",
            target_audience=["family_caregivers"],
        ),
        PricingTierCard(
            tier_id="clinic",
            title="Клиника",
            subtitle="B2B: branded reports, workflow, API",
            monthly_price=None,
            yearly_price=None,
            currency=curr,
            bullet_points=[
                "Branded отчёты",
                "Режим оператора",
                "Админка, экспорты, качество",
                "API / интеграции",
            ],
            recommended=False,
            cta="Связаться",
            target_audience=["clinics_b2b"],
        ),
    ]


def get_tier_card_by_id(tier_id: str, currency: str | None = None) -> PricingTierCard | None:
    for c in get_pricing_tier_cards(currency):
        if c.tier_id == tier_id:
            return c
    return None
