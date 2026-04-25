from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.lab_user_report_formatter import (
    build_user_lab_report,
    render_user_lab_report_text,
    sanitize_doctor_hypotheses_for_user,
)


def postprocess_lab_analysis_for_user(
    *,
    lab_rows: List[Dict[str, Any]],
    doctor_hypotheses: List[Dict[str, Any]] | List[str],
    symptoms: Optional[List[str]] = None,
    user_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    symptoms = symptoms or []
    user_profile = user_profile or {}

    clean_hypotheses = sanitize_doctor_hypotheses_for_user(
        doctor_hypotheses,
        symptoms=symptoms,
    )

    report = build_user_lab_report(
        lab_rows=lab_rows,
        context={
            "symptoms": symptoms,
            "user_profile": user_profile,
            "clean_hypotheses": clean_hypotheses,
        },
    )

    return {
        "user_report_structured": {
            "severity": report.severity,
            "headline": report.headline,
            "blocks": [
                {
                    "kind": block.kind,
                    "title": block.title,
                    "items": block.items,
                }
                for block in report.blocks
            ],
        },
        "user_report_text": render_user_lab_report_text(report),
        "user_hypotheses": clean_hypotheses,
        "debug_user_report": report.hidden_debug,
    }
