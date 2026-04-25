"""
Сбор конверсионных сигналов из контекста пользователя, clinical output и product.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.onboarding_models import ConversionSignal


def collect_conversion_signals(
    user_context: Dict[str, Any],
    clinical_output: Dict[str, Any],
    product_context: Dict[str, Any],
) -> List[ConversionSignal]:
    """
    Собрать сигналы для conversion engine: загрузка, просмотр отчёта, follow-up, locked feature и т.д.
    """
    signals: List[ConversionSignal] = []
    out = clinical_output or {}
    prod = product_context or {}
    user = user_context or {}

    has_upload = bool(user.get("has_uploaded_files") or user.get("documents_count") or user.get("lab_rows_count"))
    if has_upload:
        signals.append(ConversionSignal(signal_id="lab_uploaded", signal_type="lab_uploaded", weight=1.0, metadata={"first": user.get("first_upload")}))

    if out.get("user_report_structured") or out.get("care_plan"):
        signals.append(ConversionSignal(signal_id="report_viewed", signal_type="report_viewed", weight=1.0))

    gated = prod.get("gated_features") or []
    if "physician_report" in gated and (out.get("physician_report") is None and out.get("physician_report_text") is None):
        signals.append(ConversionSignal(signal_id="physician_report_teased", signal_type="physician_report_teased", weight=0.9))

    if user.get("is_returning_user"):
        signals.append(ConversionSignal(signal_id="followup_return", signal_type="followup_return", weight=1.0))
        signals.append(ConversionSignal(signal_id="repeat_usage", signal_type="repeat_usage", weight=0.8))

    if out.get("continuity_summary") and (out.get("continuity_summary") or {}).get("recent_trends"):
        signals.append(ConversionSignal(signal_id="trend_value", signal_type="trend_value", weight=0.9))

    if out.get("care_plan"):
        signals.append(ConversionSignal(signal_id="care_plan_viewed", signal_type="care_plan_viewed", weight=0.5))

    if user.get("pending_labs_uploaded"):
        signals.append(ConversionSignal(signal_id="followup_completed", signal_type="followup_return", weight=1.0))

    multi_file = (user.get("documents_count") or 0) + (user.get("lab_files_count") or 0) > 1
    if multi_file:
        signals.append(ConversionSignal(signal_id="multi_file_upload", signal_type="multi_file_upload", weight=0.7))

    return signals


def detect_first_value(clinical_output: Dict[str, Any] | None) -> bool:
    """
    First value достигнут, если пользователь получил хотя бы одно из:
    user_report_structured, care_plan, полезные questions, recommended_labs, безопасный итог.
    """
    if not clinical_output:
        return False
    out = clinical_output
    if out.get("user_report_structured") and (out.get("user_report_structured") or {}).get("blocks"):
        return True
    if out.get("care_plan") and (out.get("care_plan") or {}).get("actions"):
        return True
    if out.get("questions") and len(out.get("questions") or []) > 0:
        return True
    if out.get("recommended_labs") and len(out.get("recommended_labs") or []) > 0:
        return True
    if (out.get("final_user_message") or "").strip() and out.get("state") not in ("needs_more_data", ""):
        return True
    if out.get("user_hypotheses") and len(out.get("user_hypotheses") or []) > 0:
        return True
    return False
