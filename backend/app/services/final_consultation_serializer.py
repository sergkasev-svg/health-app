from __future__ import annotations

from typing import Any


class FinalConsultationSerializer:
    """
    Creates one final package for the app:
    - patient view
    - doctor view
    - machine-readable block
    """

    def serialize(
        self,
        *,
        patient_text: str,
        doctor_report: dict[str, Any],
        care_level: str,
        confidence: dict[str, Any],
        severity: dict[str, Any],
        timeline: dict[str, Any],
        journal_summary: dict[str, Any],
        lab_bridge: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "patient_view": {
                "text": patient_text,
                "care_level": care_level,
            },
            "doctor_view": doctor_report,
            "machine_view": {
                "care_level": care_level,
                "confidence": confidence,
                "severity": severity,
                "timeline": timeline,
                "journal_summary": journal_summary,
                "lab_bridge": lab_bridge,
            },
        }

