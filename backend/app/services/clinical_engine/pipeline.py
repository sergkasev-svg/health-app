"""
Единый pipeline: document classifier → extractor → normalizer → profile router
→ profile-specific rules → finding normalizer → risk synthesizer → report builder → (renderer снаружи).
Вход: текст документа (extracted_text). Выход: ReportModel или None.
Renderer ничего не решает; вся клиническая логика до него.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.services.clinical_engine.classifier import classify_document
from app.services.clinical_engine.contracts import ClinicalCoreResult, DocumentType, ReportModel
from app.services.clinical_engine.clinical_rules.integration import apply_clinical_rules_to_core
from app.services.clinical_engine.extractor import extract_blood_biochemistry
from app.services.clinical_engine.report_builder import build_report_from_values
from app.services.clinical_engine.renderers.physician_renderer import render_physician_report
from app.services.clinical_engine.renderers.patient_safe_renderer import render_patient_safe_report
from app.services.clinical_engine.router import get_profile


def run_blood_biochemistry_pipeline(extracted_text: str) -> Optional[ReportModel]:
    """
    Запускает pipeline для биохимии крови (biochemistry_blood / lipid_panel).
    classifier → extractor → router → profile rules (в report_builder) → finding normalizer → risk synthesizer → report builder.
    """
    if not (extracted_text or "").strip():
        return None

    doc_type = classify_document(extracted_text)
    if doc_type not in (DocumentType.BIOCHEMISTRY_BLOOD, DocumentType.LIPID_PANEL):
        return None

    values = extract_blood_biochemistry(extracted_text)
    if len(values) < 3:
        return None

    profile = get_profile(doc_type, values)
    if profile not in ("lipid_panel", "biochemistry_blood"):
        return None

    return build_report_from_values(document_type=doc_type, profile=profile, values=values)


def report_model_to_clinical_core(
    model: ReportModel,
    *,
    extracted_text: str = "",
    patient_meta: Optional[Dict[str, Any]] = None,
) -> ClinicalCoreResult:
    """Единый core из pipeline: один источник правды для physician и patient-safe рендеров."""
    normalized_values = {v.code: v for v in (model.raw_values or [])}
    core = ClinicalCoreResult(
        document_type=model.document_type,
        profile=model.profile or "",
        normalized_values=normalized_values,
        final_findings=list(model.key_findings or []),
        working_hypotheses=list(model.working_hypotheses or []),
        next_steps=list(model.next_steps or []),
        risk=model.risk_assessment,
        limitations=list(model.limitations or []),
        urgency=list(model.urgency or []),
        summary=model.summary or "",
        group_interpretations=list(model.group_interpretations or []),
    )
    return apply_clinical_rules_to_core(core, extracted_text, patient_meta)


def report_model_to_legacy_dict(
    model: ReportModel,
    filename: str = "",
    *,
    extracted_text: str = "",
    patient_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Physician report из единого core: model → ClinicalCoreResult → physician_renderer.
    Формат совместим с document_physician_report.
    """
    core = report_model_to_clinical_core(model, extracted_text=extracted_text, patient_meta=patient_meta)
    return render_physician_report(core, filename)


def build_dual_reports(
    model: ReportModel,
    filename: str = "",
    *,
    extracted_text: str = "",
    patient_meta: Optional[Dict[str, Any]] = None,
) -> tuple[ClinicalCoreResult, Dict[str, Any], Dict[str, Any]]:
    """
    Один core → два выхода: physician report и patient-safe report.
    Оба строятся из одного ClinicalCoreResult; разница только в подаче.
    """
    core = report_model_to_clinical_core(model, extracted_text=extracted_text, patient_meta=patient_meta)
    physician_report = render_physician_report(core, filename)
    patient_report = render_patient_safe_report(core)
    return core, physician_report, patient_report
