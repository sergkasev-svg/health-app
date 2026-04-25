"""
UI-level routing: один clinical core → три канала показа (patient, physician, gated).
Не меняет клинический смысл; только раскладка по видимости. Single source of truth — core.
"""
from __future__ import annotations

from app.services.clinical_engine.contracts import ClinicalCoreResult, UIRouteResult
from app.services.clinical_engine.ui_policy.gating_policy import build_gated_payload
from app.services.clinical_engine.ui_policy.patient_policy import build_patient_payload
from app.services.clinical_engine.ui_policy.physician_policy import build_physician_payload


def route_core_to_ui(core: ClinicalCoreResult, filename: str = "") -> UIRouteResult:
    """
    Строит UIRouteResult из одного core:
    - patient: safe summary, findings, what_it_means, actions, red_flags (urgent всегда в red_flags)
    - physician: full report
    - gated: low-confidence hypotheses, confirmation-dependent, internal reasoning
    Выходы не противоречат друг другу; разница только в глубине и видимости.
    """
    patient = build_patient_payload(core)
    physician = build_physician_payload(core, filename)
    gated = build_gated_payload(core)

    return UIRouteResult(
        patient_summary=patient.get("summary") or "",
        patient_findings=patient.get("findings") or [],
        patient_what_it_means=patient.get("what_it_means") or "",
        patient_actions=patient.get("actions") or [],
        patient_red_flags=patient.get("red_flags") or [],
        physician_report=physician,
        gated_sections=gated.get("gated_sections") or [],
        gated_hypotheses=gated.get("gated_hypotheses") or [],
        gated_reasoning=gated.get("gated_reasoning") or [],
    )


def get_patient_visible_payload(route: UIRouteResult) -> dict:
    """Словарь для UI «то, что видит пациент»."""
    return {
        "summary": route.patient_summary,
        "findings": route.patient_findings,
        "what_it_means": route.patient_what_it_means,
        "actions": route.patient_actions,
        "red_flags": route.patient_red_flags,
    }


def get_physician_visible_payload(route: UIRouteResult) -> dict:
    """Словарь для UI «Отчёт для врача»."""
    return route.physician_report


def get_gated_payload(route: UIRouteResult) -> dict:
    """Словарь для UI «скрыто до подтверждения» / внутренний аудит."""
    return {
        "gated_hypotheses": route.gated_hypotheses,
        "gated_sections": route.gated_sections,
        "gated_reasoning": route.gated_reasoning,
    }
