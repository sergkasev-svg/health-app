"""
Дефолтные планы подписок: free, plus, pro, family, clinic.
Внутренний слой без привязки к конкретной платёжной системе.
"""
from __future__ import annotations

from app.services.product_feature_registry import (
    FEATURE_CARE_PLAN_SHORT,
    FEATURE_CONTINUITY_SUMMARY,
    FEATURE_EMERGENCY_TRIAGE,
    FEATURE_LAB_INTERPRETATION_BASIC,
    FEATURE_MEMORY_LIMITED,
    FEATURE_PHYSICIAN_REPORT,
    FEATURE_SYMPTOM_CHAT_BASIC,
    FEATURE_TRENDS_BASIC,
)
from app.services.product_models import PlanFeature, SubscriptionPlan


def get_default_plans() -> list[SubscriptionPlan]:
    return [
        SubscriptionPlan(
            plan_id="free",
            name="Бесплатный",
            tier="free",
            monthly_price=0.0,
            yearly_price=0.0,
            currency="RUB",
            features=[
                PlanFeature(FEATURE_SYMPTOM_CHAT_BASIC, True, 10),
                PlanFeature(FEATURE_EMERGENCY_TRIAGE, True, None),
                PlanFeature(FEATURE_LAB_INTERPRETATION_BASIC, True, 3),
                PlanFeature(FEATURE_CARE_PLAN_SHORT, True, None),
                PlanFeature(FEATURE_MEMORY_LIMITED, True, 7),
            ],
        ),
        SubscriptionPlan(
            plan_id="plus",
            name="Плюс",
            tier="plus",
            monthly_price=299.0,
            yearly_price=2990.0,
            currency="RUB",
            features=[
                PlanFeature(FEATURE_SYMPTOM_CHAT_BASIC, True, None),
                PlanFeature(FEATURE_EMERGENCY_TRIAGE, True, None),
                PlanFeature(FEATURE_LAB_INTERPRETATION_BASIC, True, None),
                PlanFeature(FEATURE_CARE_PLAN_SHORT, True, None),
                PlanFeature(FEATURE_MEMORY_LIMITED, True, None),
                PlanFeature(FEATURE_CONTINUITY_SUMMARY, True, None),
                PlanFeature(FEATURE_TRENDS_BASIC, True, None),
            ],
        ),
        SubscriptionPlan(
            plan_id="pro",
            name="Про",
            tier="pro",
            monthly_price=599.0,
            yearly_price=5990.0,
            currency="RUB",
            features=[
                PlanFeature(FEATURE_PHYSICIAN_REPORT, True, None),
                PlanFeature(FEATURE_CARE_PLAN_SHORT, True, None),
                PlanFeature(FEATURE_CONTINUITY_SUMMARY, True, None),
                PlanFeature(FEATURE_TRENDS_BASIC, True, None),
            ],
        ),
        SubscriptionPlan(
            plan_id="family",
            name="Семья",
            tier="family",
            monthly_price=799.0,
            yearly_price=7990.0,
            currency="RUB",
            features=[],
        ),
        SubscriptionPlan(
            plan_id="clinic",
            name="Клиника",
            tier="clinic",
            monthly_price=None,
            yearly_price=None,
            currency="RUB",
            features=[],
        ),
    ]


def get_plan_by_id(plan_id: str) -> SubscriptionPlan | None:
    for p in get_default_plans():
        if p.plan_id == plan_id:
            return p
    return None
