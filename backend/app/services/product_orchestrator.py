"""
Product Orchestrator: оценка доступа, применение гейтов к clinical output, апгрейд-подсказки.
Launch/GTM: pricing_cards, launch_flags, launch block (hero, trust, faq, b2b_cta).
Safety: emergency/red flags не гейтятся.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.b2b_offer_registry import get_b2b_cta_copy
from app.services.landing_copy_registry import get_hero_section, get_how_it_works, get_trust_section
from app.services.support_faq_registry import get_faq_highlights

from app.services.entitlement_service import EntitlementService
from app.services.launch_config import get_launch_flags
from app.services.paywall_copy_builder import build_offer_cards, build_upgrade_prompt
from app.services.product_gating_policy import should_gate_physician_report
from app.services.product_models import UserEntitlements
from app.services.product_message_builder import ProductMessageBuilder


class ProductOrchestrator:
    """
    После clinical pipeline: проверить entitlements, применить гейты,
    вернуть output с product.* и (при необходимости) урезанными платными полями.
    """

    def __init__(self):
        self._entitlement = EntitlementService()

    def evaluate_access(
        self,
        user_id: Optional[str],
        requested_features: List[str],
    ) -> Dict[str, Any]:
        """Проверить доступ к списку фич. Возвращает dict с allowed/gated по каждой."""
        ent = self._entitlement.get_user_entitlements(user_id)
        result = {}
        for f in requested_features:
            dec = self._entitlement.can_use_feature(ent, f)
            result[f] = {"allowed": dec.allowed, "upgrade_required": dec.upgrade_required}
        return result

    def apply_gates(
        self,
        clinical_output: Dict[str, Any],
        entitlements: UserEntitlements,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Применить гейты к копии clinical output. Не мутировать исходный.
        Emergency/red flags не трогаем; physician_report при гейте — скрыть или teaser.
        """
        out = dict(clinical_output)
        state = out.get("state")
        urgency = out.get("urgency")
        red_flags = list(context.get("red_flags") or [])

        if should_gate_physician_report(entitlements, state, urgency, red_flags):
            if out.get("physician_report") is not None or out.get("physician_report_text"):
                out["physician_report"] = None
                out["physician_report_text"] = None
                out["_physician_report_gated"] = True
                out.setdefault("_gated_features", []).append("physician_report")

        tier = entitlements.tier or "free"
        builder = ProductMessageBuilder()
        out["product"] = {
            "active_tier": tier,
            "gated_features": out.get("_gated_features", []),
            "available_features": list(entitlements.features.keys()) if isinstance(entitlements.features, dict) else [],
            "upgrade_prompts": self._prompts_for_gated(out.get("_gated_features", []), tier),
            "offers": build_offer_cards(entitlements),
            "pricing_cards": builder.build_pricing_cards(),
            "launch_flags": get_launch_flags(),
        }
        out["launch"] = _build_launch_block()
        out.pop("_gated_features", None)
        out.pop("_physician_report_gated", None)
        return out

    def _prompts_for_gated(self, gated: List[str], tier: str) -> List[Dict[str, Any]]:
        prompts = []
        for f in gated:
            prompts.append(build_upgrade_prompt(f, tier))
        return prompts

    def build_upgrade_prompts(
        self,
        clinical_output: Dict[str, Any],
        entitlements: UserEntitlements,
    ) -> List[Dict[str, Any]]:
        """Подсказки об апгрейде по заблокированным фичам."""
        gated = clinical_output.get("_gated_features") or []
        return self._prompts_for_gated(gated, entitlements.tier or "free")


def _build_launch_block() -> Dict[str, Any]:
    """Блок launch для API: hero, how_it_works, trust_points, faq_highlights, b2b_cta."""
    flags = get_launch_flags()
    return {
        "hero": get_hero_section(),
        "how_it_works": get_how_it_works(),
        "trust_points": get_trust_section().get("points", []),
        "faq_highlights": get_faq_highlights(3),
        "b2b_cta": get_b2b_cta_copy() if flags.get("show_b2b_cta") else None,
    }
