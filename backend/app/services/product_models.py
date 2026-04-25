"""
Модели продукта и биллинга: планы, права доступа, офферы, решения по гейтингу.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PlanFeature:
    key: str = ""
    enabled: bool = True
    limit: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class SubscriptionPlan:
    plan_id: str = ""
    name: str = ""
    tier: str = "free"  # free / plus / pro / family / clinic / enterprise
    monthly_price: Optional[float] = None
    yearly_price: Optional[float] = None
    currency: Optional[str] = None
    features: List[PlanFeature] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "name": self.name,
            "tier": self.tier,
            "monthly_price": self.monthly_price,
            "yearly_price": self.yearly_price,
            "currency": self.currency,
            "features": [
                {"key": f.key, "enabled": f.enabled, "limit": f.limit}
                for f in self.features
            ],
        }


@dataclass
class UserEntitlements:
    user_id: Optional[str] = None
    active_plan_id: str = "free"
    tier: str = "free"
    features: Dict[str, Any] = field(default_factory=dict)
    usage_counters: Dict[str, Any] = field(default_factory=dict)
    billing_status: Optional[str] = None
    expires_at: Optional[str] = None


@dataclass
class ProductOffer:
    offer_id: str = ""
    title: str = ""
    description: str = ""
    price: Optional[float] = None
    currency: Optional[str] = None
    offer_type: str = "subscription"  # subscription / one_time / b2b / upsell
    target_tiers: List[str] = field(default_factory=list)
    feature_unlocks: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "offer_id": self.offer_id,
            "title": self.title,
            "description": self.description,
            "price": self.price,
            "currency": self.currency or "RUB",
            "offer_type": self.offer_type,
            "target_tiers": self.target_tiers,
            "feature_unlocks": self.feature_unlocks,
            "cta": "Подробнее" if self.offer_type == "subscription" else "Купить",
        }


@dataclass
class MonetizationDecision:
    allowed: bool = True
    reason: Optional[str] = None
    upgrade_required: bool = False
    suggested_offer_id: Optional[str] = None
    soft_gate: bool = False  # показать teaser
    hard_gate: bool = False  # полностью скрыть
