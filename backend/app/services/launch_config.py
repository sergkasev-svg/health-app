"""
Feature/config флаги для запуска. Безопасные defaults.
"""
from __future__ import annotations

from typing import Any, Dict

from app.core.settings import get_settings


def get_launch_flags() -> Dict[str, bool]:
    """Флаги запуска. При отсутствии настроек — консервативные значения."""
    try:
        # Можно вынести в env: LAUNCH_MODE_ENABLED, SHOW_PRICING_PAGE и т.д.
        s = get_settings()
        return {
            "launch_mode_enabled": getattr(s, "LAUNCH_MODE_ENABLED", None) or False,
            "show_pricing_page": getattr(s, "SHOW_PRICING_PAGE", None) is not False,
            "show_waitlist": getattr(s, "SHOW_WAITLIST", None) or False,
            "show_b2b_cta": getattr(s, "SHOW_B2B_CTA", None) or False,
            "show_family_cta": getattr(s, "SHOW_FAMILY_CTA", None) or False,
            "show_physician_report_teaser": True,
            "enable_intro_onboarding": True,
            "enable_launch_banner": getattr(s, "ENABLE_LAUNCH_BANNER", None) or False,
            "enable_founder_offer": getattr(s, "ENABLE_FOUNDER_OFFER", None) or False,
            "enable_discount_placeholders": getattr(s, "ENABLE_DISCOUNT_PLACEHOLDERS", None) or False,
        }
    except Exception:
        return {
            "launch_mode_enabled": False,
            "show_pricing_page": True,
            "show_waitlist": False,
            "show_b2b_cta": False,
            "show_family_cta": False,
            "show_physician_report_teaser": True,
            "enable_intro_onboarding": True,
            "enable_launch_banner": False,
            "enable_founder_offer": False,
            "enable_discount_placeholders": False,
        }
