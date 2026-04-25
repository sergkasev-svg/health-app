"""
Сборка согласованного ReportModel из findings и values.
Title/subtitle строго по document_type и profile; никаких generic fallback при наличии findings.
Единая точка: build_report_from_values(document_type, profile, values) — classifier → extractor → router → profile rules → normalizer → risk synthesizer → здесь.
"""
from __future__ import annotations

from typing import List, Union

from app.services.clinical_engine.contracts import DocumentType, Finding, LabValue, ReportModel
from app.services.clinical_engine.finding_normalizer import normalize_findings
from app.services.clinical_engine.risk_engine import run_risk_engine, prioritize_next_steps
from app.services.clinical_engine.risk_synthesizer import (
    build_group_interpretations,
    build_limitations,
    build_next_steps,
    build_summary,
    build_working_hypotheses,
    synthesize_risk,
)
from app.services.clinical_engine.text_templates import get_report_title_subtitle


def _get_findings_for_profile(profile: str, values: List[LabValue]) -> List[Finding]:
    """Профиль-специфичные правила → список findings."""
    if profile == "lipid_panel":
        from app.services.clinical_engine.profiles.lipid_panel import interpret_lipids
        return interpret_lipids(values)
    if profile == "biochemistry_blood":
        from app.services.clinical_engine.profiles.biochemistry_blood import interpret_biochemistry_blood
        return interpret_biochemistry_blood(values)
    if profile == "generic_lab":
        from app.services.clinical_engine.profiles.fallback_generic_lab import interpret_fallback_generic
        return interpret_fallback_generic(values)
    return []


def build_report_from_values(
    document_type: Union[DocumentType, str],
    profile: str,
    values: List[LabValue],
) -> ReportModel:
    """
    Один вход: (document_type, profile, values). Внутри: profile rules → normalizer → synthesize_risk → ReportModel.
    Вся клиническая логика до renderer.
    """
    doc_type_str = document_type.value if isinstance(document_type, DocumentType) else document_type
    findings = _get_findings_for_profile(profile, values)
    findings = normalize_findings(findings)

    summary, working_hypotheses, next_steps = synthesize_risk(findings, values, profile)
    limitations = build_limitations(profile, len(findings) > 0)
    group_interpretations = build_group_interpretations(findings, values, profile)
    title, subtitle = get_report_title_subtitle(doc_type_str, profile)

    # Risk engine: только на основе values, findings, hypotheses — не создаёт новых findings
    risk_assessment = run_risk_engine(
        values=values,
        findings=findings,
        working_hypotheses=working_hypotheses,
        profile=profile,
        document_type=doc_type_str,
    )
    next_steps = prioritize_next_steps(next_steps, risk_assessment)

    key_findings = [f for f in findings if f.include_in_key_table]
    borderline = [f for f in findings if f.severity in ("mild", "info") and f not in key_findings]

    return ReportModel(
        document_type=doc_type_str,
        profile=profile,
        title=title,
        subtitle=subtitle,
        summary=summary,
        key_findings=key_findings,
        borderline_findings=borderline,
        group_interpretations=group_interpretations,
        working_hypotheses=working_hypotheses,
        next_steps=next_steps,
        limitations=limitations,
        urgency=[risk_assessment.urgency] if risk_assessment.urgency and risk_assessment.urgency != "non_urgent" else [],
        raw_values=values,
        risk_assessment=risk_assessment,
    )


def build_report(
    document_type: Union[DocumentType, str],
    profile: str,
    findings: List[Finding],
    values: List[LabValue],
) -> ReportModel:
    """
    Один canonical список findings → summary, key_findings, working_hypotheses, next_steps.
    Запрет: при наличии клинически значимых findings не подставлять «нет значимых отклонений».
    """
    doc_type_str = document_type.value if isinstance(document_type, DocumentType) else document_type
    title, subtitle = get_report_title_subtitle(doc_type_str, profile)

    key_findings = [f for f in findings if f.include_in_key_table]
    borderline = [f for f in findings if f.severity in ("mild", "info") and f not in key_findings]
    if not borderline:
        borderline = []

    summary = build_summary(findings, values, profile)
    working_hypotheses = build_working_hypotheses(findings, profile)
    next_steps = build_next_steps(findings, profile)
    limitations = build_limitations(profile, len(findings) > 0)
    group_interpretations = build_group_interpretations(findings, values, profile)

    return ReportModel(
        document_type=doc_type_str,
        profile=profile,
        title=title,
        subtitle=subtitle,
        summary=summary,
        key_findings=key_findings,
        borderline_findings=borderline,
        group_interpretations=group_interpretations,
        working_hypotheses=working_hypotheses,
        next_steps=next_steps,
        limitations=limitations,
        urgency=[],
        raw_values=values,
    )
