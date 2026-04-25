"""
Clinical engine: согласованная цепочка
classifier → extractor → normalizer → router → rules → risk_synthesizer → report_builder.
Один canonical findings list; report title только от document_type; запрет ложного fallback.
"""
from app.services.clinical_engine.contracts import (
    ClinicalCoreResult,
    ClinicalPattern,
    DocumentType,
    Finding,
    Hypothesis,
    LabValue,
    NextStep,
    OverallRisk,
    ReportModel,
    RiskAssessment,
    UIRouteResult,
)
from app.services.clinical_engine.clinical_rules.integration import apply_clinical_rules_to_core
from app.services.clinical_engine.pipeline import (
    build_dual_reports,
    report_model_to_clinical_core,
    report_model_to_legacy_dict,
    run_blood_biochemistry_pipeline,
)
from app.services.clinical_engine.classifier import classify_document
from app.services.clinical_engine.risk_engine import run_risk_engine, prioritize_next_steps
from app.services.clinical_engine.renderers import render_patient_safe_report, render_physician_report
from app.services.clinical_engine.ui_routing import (
    route_core_to_ui,
    get_patient_visible_payload,
    get_physician_visible_payload,
    get_gated_payload,
)
from app.services.clinical_engine.unified_pipeline import UnifiedClinicalPipeline, run_unified_clinical_pipeline
from app.services.clinical_engine.unified_contract import (
    UnifiedClinicalPayload,
    serialize_aggregate_report_to_unified_payload,
    serialize_clinical_core_to_ui,
)

__all__ = [
    "ClinicalCoreResult",
    "ClinicalPattern",
    "apply_clinical_rules_to_core",
    "DocumentType",
    "Finding",
    "Hypothesis",
    "LabValue",
    "NextStep",
    "OverallRisk",
    "ReportModel",
    "RiskAssessment",
    "UIRouteResult",
    "classify_document",
    "run_blood_biochemistry_pipeline",
    "report_model_to_legacy_dict",
    "report_model_to_clinical_core",
    "build_dual_reports",
    "run_risk_engine",
    "prioritize_next_steps",
    "render_physician_report",
    "render_patient_safe_report",
    "route_core_to_ui",
    "get_patient_visible_payload",
    "get_physician_visible_payload",
    "get_gated_payload",
    "UnifiedClinicalPipeline",
    "run_unified_clinical_pipeline",
    "UnifiedClinicalPayload",
    "serialize_aggregate_report_to_unified_payload",
    "serialize_clinical_core_to_ui",
]
