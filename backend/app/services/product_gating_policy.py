"""
Политика гейтинга: что никогда не блокировать (safety), что можно ограничивать.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.product_feature_registry import (
    FEATURE_PHYSICIAN_REPORT,
    FEATURE_LAB_INTERPRETATION_ADVANCED,
    FEATURE_REPORT_EXPORT,
    FEATURE_FAMILY_MULTI_PROFILE,
)
from app.services.product_models import UserEntitlements


# Никогда не блокировать: emergency triage, red flags, базовые safe recommendations
def _is_safety_critical(state: Optional[str], urgency: Optional[str], red_flags: Any) -> bool:
    if state == "emergency":
        return True
    if (urgency or "").lower() == "high":
        return True
    if red_flags and len(red_flags) > 0:
        return True
    return False


def should_gate_physician_report(
    entitlements: Optional[UserEntitlements],
    state: Optional[str] = None,
    urgency: Optional[str] = None,
    red_flags: Optional[list] = None,
) -> bool:
    """Решать, гейтить ли physician_report. При emergency/high/red_flags — не гейтить."""
    if _is_safety_critical(state, urgency, red_flags):
        return False
    if not entitlements:
        return True
    allowed = (entitlements.features or {}).get(FEATURE_PHYSICIAN_REPORT, False)
    return not allowed


def should_gate_advanced_analysis(
    entitlements: Optional[UserEntitlements],
    state: Optional[str] = None,
    red_flags: Optional[list] = None,
) -> bool:
    if _is_safety_critical(state, None, red_flags):
        return False
    if not entitlements:
        return True
    allowed = (entitlements.features or {}).get(FEATURE_LAB_INTERPRETATION_ADVANCED, False)
    return not allowed


def should_gate_export(
    entitlements: Optional[UserEntitlements],
) -> bool:
    if not entitlements:
        return True
    return not (entitlements.features or {}).get(FEATURE_REPORT_EXPORT, False)


def should_gate_family_profiles(
    entitlements: Optional[UserEntitlements],
) -> bool:
    if not entitlements:
        return True
    return not (entitlements.features or {}).get(FEATURE_FAMILY_MULTI_PROFILE, False)
