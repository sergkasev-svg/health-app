"""
Patient-visible channel: safe summary, simple findings, action steps, urgent warnings.
Urgent items always surface. No hypotheses as diagnosis. No contradiction with physician.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.clinical_engine.contracts import ClinicalCoreResult
from app.services.clinical_engine.renderers.patient_safe_renderer import render_patient_safe_report


def build_patient_payload(core: ClinicalCoreResult) -> Dict[str, Any]:
    """
    Всё, что пациент видит сразу: summary, findings, what it means, actions, red flags.
    Строится из того же core через patient-safe renderer; routing не меняет смысл.
    Urgent items всегда попадают в red_flags.
    """
    report = render_patient_safe_report(core)
    sections = (report.get("patient_report_structured") or {}).get("sections") or []
    what_it_means = next((s.get("content", "") for s in sections if "значит" in (s.get("title") or "")), "")
    findings = next((s.get("items", []) for s in sections if "отклонено" in (s.get("title") or "")), [])
    return {
        "summary": report.get("main_point") or "",
        "findings": findings,
        "what_it_means": what_it_means,
        "actions": report.get("next_steps_patient") or [],
        "red_flags": report.get("red_flags") or [],
    }
