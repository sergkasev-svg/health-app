"""
События продуктовой аналитики. Safe no-op при недоступности аналитики.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

EVENT_SIGNUP_STARTED = "signup_started"
EVENT_SIGNUP_COMPLETED = "signup_completed"
EVENT_LAB_UPLOAD_STARTED = "lab_upload_started"
EVENT_LAB_UPLOAD_COMPLETED = "lab_upload_completed"
EVENT_FIRST_REPORT_GENERATED = "first_report_generated"
EVENT_PHYSICIAN_REPORT_VIEWED = "physician_report_viewed"
EVENT_UPGRADE_PROMPT_SHOWN = "upgrade_prompt_shown"
EVENT_UPGRADE_CLICKED = "upgrade_clicked"
EVENT_PLAN_ACTIVATED = "plan_activated"
EVENT_CARE_PLAN_OPENED = "care_plan_opened"
EVENT_DOCTOR_REPORT_EXPORTED = "doctor_report_exported"
EVENT_FOLLOWUP_RETURNED = "followup_returned"
EVENT_FAMILY_PROFILE_CREATED = "family_profile_created"

# Onboarding + conversion
EVENT_ONBOARDING_STARTED = "onboarding_started"
EVENT_ONBOARDING_STEP_COMPLETED = "onboarding_step_completed"
EVENT_FIRST_VALUE_REACHED = "first_value_reached"
EVENT_FIRST_UPGRADE_PROMPT_SHOWN = "first_upgrade_prompt_shown"
EVENT_RETURN_USER_DETECTED = "return_user_detected"
EVENT_FOLLOWUP_CONVERSION_SIGNAL = "followup_conversion_signal"
EVENT_LOCKED_FEATURE_TEASER_SHOWN = "locked_feature_teaser_shown"


def track_product_event(event_name: str, payload: Dict[str, Any] | None = None) -> None:
    """
    Отправить событие в аналитику. При недоступности сервиса — silent no-op, не падать.
    """
    try:
        payload = payload or {}
        # TODO: интеграция с Amplitude/Mixpanel/внутренний логгер
        logger.info("product_event %s %s", event_name, payload)
    except Exception:
        pass
