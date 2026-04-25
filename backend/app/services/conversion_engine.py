"""
Conversion Engine: когда показывать апгрейд. После ценности, не при emergency.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.conversion_copy_builder import (
    build_followup_upgrade_copy,
    build_locked_feature_teaser,
    build_post_value_upgrade_copy,
    build_repeat_usage_upgrade_copy,
)
from app.services.onboarding_models import ConversionDecision, ConversionSignal, OnboardingState
from app.services.product_models import UserEntitlements


PLACEMENT_AFTER_FIRST_RESULT = "after_first_result"
PLACEMENT_AFTER_REPORT = "after_report"
PLACEMENT_AFTER_LOCKED_FEATURE = "after_locked_feature"
PLACEMENT_FOLLOWUP_RETURN = "followup_return"
PLACEMENT_DASHBOARD_BANNER = "dashboard_banner"
PLACEMENT_REPORT_FOOTER = "report_footer"


class ConversionEngine:
    """
    Решение: показывать ли апгрейд, где и с каким сообщением.
    Не показывать до first_value, при emergency, слишком рано.
    """

    def decide(
        self,
        onboarding_state: Optional[OnboardingState],
        signals: List[ConversionSignal],
        entitlements: Optional[UserEntitlements],
        clinical_output: Optional[Dict[str, Any]],
    ) -> ConversionDecision:
        out = clinical_output or {}
        state = onboarding_state or OnboardingState()
        sigs = signals or []

        if out.get("state") == "emergency":
            return ConversionDecision(should_show_upgrade=False, reason="emergency")

        if (out.get("urgency") or "").lower() == "high":
            return ConversionDecision(should_show_upgrade=False, reason="high_urgency")

        if out.get("red_flags"):
            return ConversionDecision(should_show_upgrade=False, reason="red_flags")

        tier = (entitlements.tier if entitlements else "free") or "free"
        if tier not in ("free", "plus"):
            return ConversionDecision(should_show_upgrade=False, reason="already_paid")

        first_value = state.first_value_reached or bool(out.get("user_report_structured") or out.get("care_plan") or (out.get("final_user_message") or "").strip())
        if not first_value:
            return ConversionDecision(should_show_upgrade=False, reason="no_first_value_yet")

        signal_types = [s.signal_type for s in sigs]
        placement = None
        message = None
        offer_id = "pro" if tier == "free" else "pro"
        copy_block = None

        if "physician_report_teased" in signal_types:
            placement = PLACEMENT_AFTER_LOCKED_FEATURE
            copy_block = build_locked_feature_teaser("physician_report")
            message = copy_block.get("message")
            offer_id = "pro"
        elif "followup_return" in signal_types or "repeat_usage" in signal_types:
            placement = PLACEMENT_FOLLOWUP_RETURN
            copy_block = build_repeat_usage_upgrade_copy()
            message = copy_block.get("message")
            offer_id = "plus"
        elif "trend_value" in signal_types:
            placement = PLACEMENT_REPORT_FOOTER
            copy_block = build_post_value_upgrade_copy("continuity_summary", tier)
            message = copy_block.get("message")
            offer_id = "plus"
        elif first_value and not state.first_upgrade_prompt_shown:
            placement = PLACEMENT_AFTER_FIRST_RESULT
            copy_block = build_post_value_upgrade_copy("physician_report", tier)
            message = copy_block.get("message")
            offer_id = "pro"

        if placement and message:
            return ConversionDecision(
                should_show_upgrade=True,
                timing="after_value",
                placement=placement,
                offer_id=offer_id,
                reason="conversion_eligible",
                message=message,
                offer={"offer_id": offer_id, "title": "Про" if offer_id == "pro" else "Плюс", "description": message, "price": 599 if offer_id == "pro" else 299, "currency": "RUB"},
            )
        return ConversionDecision(should_show_upgrade=False, reason="no_placement")
