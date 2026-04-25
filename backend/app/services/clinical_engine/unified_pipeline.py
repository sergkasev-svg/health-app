"""
Unified clinical pipeline — главный каркас:

material → profile → (rules via existing engines) → derived indices → risk → dual render → UI routing.

Один источник правды: ClinicalCoreResult.
Постепенно подключать cbc_engine / urinalysis_engine / lipid_engine как единые profile runners.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.clinical_engine.classifier import classify_document
from app.services.clinical_engine.contracts import ClinicalCoreResult, Hypothesis, NextStep
from app.services.clinical_engine.derived_indices import compute_derived_indices_for_document
from app.services.clinical_engine.material_protocols.material_router import route_document
from app.services.clinical_engine.pipeline import report_model_to_clinical_core, run_blood_biochemistry_pipeline
from app.services.clinical_engine.renderers.patient_safe_renderer import render_patient_safe_report
from app.services.clinical_engine.renderers.physician_renderer import render_physician_report
from app.services.clinical_engine.risk_engine import run_risk_engine
from app.services.clinical_engine.ui_routing import route_core_to_ui
from app.services.lab_value_extractor import extract_cbc_values


def _hypotheses_to_structured(core: ClinicalCoreResult) -> None:
    core.hypotheses_structured = [
        Hypothesis(code=f"h{i}", label=h, confidence=1.0, physician_visible=True, patient_visible=False)
        for i, h in enumerate(core.working_hypotheses or [])
    ]


def _next_steps_to_structured(core: ClinicalCoreResult) -> None:
    core.next_steps_structured = []
    for ns in core.next_steps or []:
        if isinstance(ns, dict):
            core.next_steps_structured.append(
                NextStep(
                    domain=str(ns.get("direction", "general")),
                    what=str(ns.get("check") or ns.get("what") or ""),
                    why=str(ns.get("why", "")),
                    priority=str(ns.get("priority", "medium")),
                )
            )


def enrich_core_unified(core: ClinicalCoreResult, text: str, routed: Any) -> ClinicalCoreResult:
    """Дополняет core полями material / derived_indices / risk_domains."""
    core.material = routed.material.value
    core.material_confidence = routed.material_confidence
    core.material_routing_reasons = list(routed.reasons or [])
    core.profile_route = routed.report_type or core.profile or ""

    rt = (routed.report_type or "").lower()
    prof = (core.profile or core.document_type or "").lower()
    if rt in ("cbc", "cbc_with_reticulocytes") or "cbc" in prof:
        rows = extract_cbc_values(text)
        di = compute_derived_indices_for_document(text, rows)
        core.derived_indices = [d.model_dump() for d in di]

    if core.risk and core.risk.domain_risks:
        core.risk_domains = list(core.risk.domain_risks)

    _hypotheses_to_structured(core)
    _next_steps_to_structured(core)
    return core


class UnifiedClinicalPipeline:
    """
    Оркестратор: parse (пока = текст) → material → profile → нормализация (внутри движков)
    → findings → derived indices → risk → ClinicalCoreResult → render ×2 → UI route.
    """

    def parse(self, raw_document: str) -> Dict[str, Any]:
        """Минимальный parse: вся строка как extracted text. Далее: parsing/document_parser."""
        text = (raw_document or "").strip()
        return {"text": text, "values": {}}

    def run(self, raw_document: str, filename: str = "") -> Dict[str, Any]:
        parsed = self.parse(raw_document)
        text: str = parsed["text"]
        if not text:
            raise ValueError("empty document")

        routed = route_document(text)

        # Путь A: биохимия крови / липиды — полный ReportModel
        model = run_blood_biochemistry_pipeline(text)
        if model is not None:
            core = report_model_to_clinical_core(model, extracted_text=text, patient_meta=None)
            vals: List = list(core.normalized_values.values())
            core.risk = run_risk_engine(
                vals,
                list(core.final_findings),
                list(core.working_hypotheses),
                core.profile or "",
                core.document_type,
            )
            core = enrich_core_unified(core, text, routed)

            physician_report = render_physician_report(core, filename)
            patient_report = render_patient_safe_report(core)
            ui_payload = route_core_to_ui(core, filename)
            return {
                "core": core.model_dump(),
                "physician_report": physician_report,
                "patient_report": patient_report,
                "ui_payload": ui_payload.model_dump(),
                "material_routing": routed.model_dump(),
            }

        # Путь B: fallback — material + enum профиль, без полного rule engine
        doc_type = classify_document(text)
        core = ClinicalCoreResult(
            document_type=doc_type.value,
            profile=doc_type.value,
            summary="",
        )
        core = enrich_core_unified(core, text, routed)

        physician_report = render_physician_report(core, filename)
        patient_report = render_patient_safe_report(core)
        ui_payload = route_core_to_ui(core, filename)
        return {
            "core": core.model_dump(),
            "physician_report": physician_report,
            "patient_report": patient_report,
            "ui_payload": ui_payload.model_dump(),
            "material_routing": routed.model_dump(),
        }


def run_unified_clinical_pipeline(raw_document: str, filename: str = "") -> Dict[str, Any]:
    """Функциональный фасад."""
    return UnifiedClinicalPipeline().run(raw_document, filename=filename)
