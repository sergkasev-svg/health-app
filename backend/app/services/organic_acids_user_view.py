from __future__ import annotations

from typing import Any, Dict

from app.services.clinical_oa_axis_routing import build_clinical_routing_output


def build_organic_acids_user_view(report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Пользовательский слой для organic acids.
    Осьовой routing (organic acids) — источник логики для UI-блоков.
    """
    routed = build_clinical_routing_output(report)
    user = routed.get("user") or {}

    return {
        "display_summary": str(user.get("display_summary") or "").strip(),
        "user_summary": str(user.get("user_summary") or "").strip(),
        "safe_next_steps": str(user.get("safe_next_steps") or "").strip(),
        "when_urgent": str(user.get("when_urgent") or "").strip(),
        "user_report_structured": user.get("user_report_structured") or {},
        "user_report_text": str(user.get("user_report_text") or "").strip(),
        "routing_debug": routed.get("ranked_axes") or [],
        "doctor_debug": routed.get("doctor") or {},
    }
