"""
Сборщик продуктовых сообщений: landing, pricing cards, paywall, onboarding, segment.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.gtm_models import PricingTierCard
from app.services.landing_copy_registry import get_landing_copy_blocks
from app.services.onboarding_copy_registry import get_onboarding_copy_blocks
from app.services.paywall_messaging_registry import get_paywall_message
from app.services.pricing_packaging import get_pricing_tier_cards
from app.services.positioning_registry import get_audience_segments, get_value_propositions


class ProductMessageBuilder:
    """Единая точка для landing, pricing, paywall, onboarding, segment messages."""

    def build_landing_messages(self, segment: Optional[str] = None) -> Dict[str, Any]:
        return get_landing_copy_blocks(segment)

    def build_pricing_cards(self, currency: Optional[str] = None) -> List[Dict[str, Any]]:
        cards = get_pricing_tier_cards(currency)
        return [c.model_dump() for c in cards]

    def build_paywall_message(
        self,
        feature_key: str,
        tier: str = "free",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        placement = (context or {}).get("placement", "gate")
        return get_paywall_message(feature_key, placement=placement, tier=tier) or {
            "message": "Функция доступна в расширенном тарифе.",
            "placement": placement,
            "cta": "Подробнее",
        }

    def build_onboarding_messages(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return get_onboarding_copy_blocks(context)

    def build_segment_messages(self, segment: str) -> Dict[str, Any]:
        segments = get_audience_segments()
        value_props = get_value_propositions()
        seg = next((s for s in segments if s.segment_id == segment), None)
        props = [v for v in value_props if v.audience == segment]
        return {
            "segment": seg.model_dump() if seg else None,
            "value_propositions": [p.model_dump() for p in props],
        }


def get_product_message_builder() -> ProductMessageBuilder:
    return ProductMessageBuilder()
