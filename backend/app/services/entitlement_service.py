"""
Сервис прав доступа: планы, фичи, счётчики использования.
Safe fallback: при отсутствии биллинга — free plan; аноним — guest/free.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.default_product_plans import get_plan_by_id
from app.services.product_feature_registry import TIER_FEATURES, get_features_for_tier
from app.services.product_models import MonetizationDecision, UserEntitlements


class EntitlementService:
    """
    Получение entitlements пользователя и проверка доступа к фичам.
    Без падения при отсутствии user_id или биллинга.
    """

    DEFAULT_PLAN_ID = "free"
    USAGE_PERIOD_DAYS = 30

    def get_user_entitlements(self, user_id: Optional[str] = None) -> UserEntitlements:
        """
        Вернуть права пользователя. Если биллинг не настроен или user_id нет — free plan.
        """
        if not user_id or not str(user_id).strip():
            return UserEntitlements(
                user_id=None,
                active_plan_id=self.DEFAULT_PLAN_ID,
                tier="free",
                features={k: True for k in get_features_for_tier("free")},
                usage_counters={},
                billing_status=None,
                expires_at=None,
            )
        # TODO: загрузка из БД/биллинга; пока всегда free
        plan_id = self.DEFAULT_PLAN_ID
        tier = "free"
        return UserEntitlements(
            user_id=user_id,
            active_plan_id=plan_id,
            tier=tier,
            features={k: True for k in get_features_for_tier(tier)},
            usage_counters={},
            billing_status=None,
            expires_at=None,
        )

    def can_use_feature(
        self,
        entitlements: UserEntitlements,
        feature_key: str,
    ) -> MonetizationDecision:
        """
        Разрешено ли использовать фичу. Emergency/red flags не проверяем здесь — их не гейтят.
        """
        if not entitlements:
            return MonetizationDecision(
                allowed=False,
                reason="Нет данных о подписке",
                upgrade_required=True,
                suggested_offer_id="plus",
                soft_gate=True,
                hard_gate=False,
            )
        tier = (entitlements.tier or "free").lower()
        allowed = entitlements.features.get(feature_key, False) if isinstance(entitlements.features, dict) else False
        if not allowed:
            allowed = feature_key in get_features_for_tier(tier)
        if allowed:
            return MonetizationDecision(allowed=True, soft_gate=False, hard_gate=False)
        return MonetizationDecision(
            allowed=False,
            reason=f"Фича {feature_key} недоступна на тарифе {tier}",
            upgrade_required=True,
            suggested_offer_id="pro" if feature_key == "physician_report" else "plus",
            soft_gate=True,
            hard_gate=False,
        )

    def increment_usage(
        self,
        entitlements: UserEntitlements,
        feature_key: str,
    ) -> None:
        """Увеличить счётчик использования фичи (для лимитов)."""
        if not entitlements or not entitlements.usage_counters:
            return
        key = f"{feature_key}_count"
        entitlements.usage_counters[key] = (entitlements.usage_counters.get(key) or 0) + 1

    def reset_periodic_usage_if_needed(self, entitlements: UserEntitlements) -> UserEntitlements:
        """При смене периода — обнулить счётчики. Пока заглушка."""
        return entitlements
