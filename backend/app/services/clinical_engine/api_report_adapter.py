from __future__ import annotations

from typing import Any

from app.services.clinical_engine.contracts_api import (
    ClinicalCoreResult,
    DerivedIndex,
    Finding,
    Hypothesis,
    LabValue,
    NextStep,
    RiskAssessment,
    SourceDocumentSummary,
)


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _norm_priority(value: Any) -> str:
    s = _safe_str(value).lower()
    if s in ("urgent", "срочно"):
        return "urgent"
    if s in ("high", "высокий"):
        return "high"
    if s in ("medium", "moderate", "средний", "контроль"):
        return "medium"
    return "low"


def _norm_risk_level(value: Any) -> str:
    s = _safe_str(value).lower()
    if s in ("urgent", "срочно"):
        return "urgent"
    if s in ("high", "высокий"):
        return "high"
    if s in ("moderate", "medium", "средний"):
        return "moderate"
    return "low"


def _norm_severity(value: Any) -> str:
    s = _safe_str(value).lower()
    if s in ("urgent", "срочно"):
        return "urgent"
    if s in ("high", "высокий", "выраженный", "выраженная"):
        return "high"
    if s in ("moderate", "medium", "средний", "умеренный", "умеренная"):
        return "moderate"
    if s in ("mild", "легкий", "лёгкий", "мягкий", "мягкая"):
        return "mild"
    if s in ("borderline", "пограничный", "пограничная"):
        return "borderline"
    return "info"


def _to_lab_value(code: str, raw: dict[str, Any]) -> LabValue:
    return LabValue(
        code=code,
        label=_safe_str(raw.get("label") or code),
        value=raw.get("value"),
        value_text=raw.get("value_text"),
        unit=raw.get("unit"),
        ref_low=raw.get("ref_low"),
        ref_high=raw.get("ref_high"),
        ref_text=raw.get("ref_text"),
        status=_safe_str(raw.get("status") or "unknown"),
        source_text=raw.get("source_text"),
    )


def _to_finding(raw: dict[str, Any]) -> Finding:
    return Finding(
        code=_safe_str(raw.get("code") or raw.get("primary_marker") or raw.get("title")),
        title=_safe_str(raw.get("title")),
        group=_safe_str(raw.get("group") or "Клиническая находка"),
        severity=_norm_severity(raw.get("severity")),
        document_id=raw.get("document_id"),
        primary_marker=raw.get("primary_marker"),
        supporting_markers=list(raw.get("supporting_markers") or []),
        value=raw.get("value"),
        reference=raw.get("reference"),
        comment=_safe_str(raw.get("comment")),
        patient_visible=bool(raw.get("patient_visible", True)),
        physician_visible=bool(raw.get("physician_visible", True)),
        requires_gating=bool(raw.get("requires_gating", False)),
        confidence=float(raw.get("confidence", 1.0)),
    )


def _to_hypothesis(raw: dict[str, Any]) -> Hypothesis:
    return Hypothesis(
        code=_safe_str(raw.get("code") or raw.get("id") or raw.get("label")),
        label=_safe_str(raw.get("label") or raw.get("hypothesis")),
        confidence=float(raw.get("confidence", 1.0)),
        document_id=raw.get("document_id"),
        patient_visible=bool(raw.get("patient_visible", False)),
        physician_visible=bool(raw.get("physician_visible", True)),
        requires_confirmation=bool(raw.get("requires_confirmation", False)),
    )


def _to_next_step(raw: dict[str, Any]) -> NextStep:
    return NextStep(
        domain=_safe_str(raw.get("domain") or raw.get("direction") or "general"),
        what=_safe_str(raw.get("what") or raw.get("check")),
        why=_safe_str(raw.get("why")),
        priority=_norm_priority(raw.get("priority") or "medium"),
        patient_visible=bool(raw.get("patient_visible", True)),
        physician_visible=bool(raw.get("physician_visible", True)),
    )


def _to_index(raw: dict[str, Any]) -> DerivedIndex:
    return DerivedIndex(
        code=_safe_str(raw.get("code") or raw.get("name")),
        title=_safe_str(raw.get("title") or raw.get("name")),
        value=raw.get("value"),
        unit=raw.get("unit"),
        status=raw.get("status"),
        interpretation=raw.get("interpretation"),
        required_markers=list(raw.get("required_markers") or []),
        missing_markers=list(raw.get("missing_markers") or []),
        confidence=_safe_str(raw.get("confidence") or "supportive"),
        patient_visible=bool(raw.get("patient_visible", False)),
        physician_visible=bool(raw.get("physician_visible", True)),
    )


def _to_risk(raw: dict[str, Any]) -> RiskAssessment:
    return RiskAssessment(
        domain=_safe_str(raw.get("domain")),
        level=_norm_risk_level(raw.get("level") or "low"),
        score=float(raw.get("score", 0)),
        label=_safe_str(raw.get("label")),
        rationale=list(raw.get("rationale") or []),
        drivers=list(raw.get("drivers") or []),
        summary=_safe_str(raw.get("summary")),
        recommended_actions=list(raw.get("recommended_actions") or []),
        patient_visible=bool(raw.get("patient_visible", True)),
        physician_visible=bool(raw.get("physician_visible", True)),
    )


def _to_source_document(raw: dict[str, Any]) -> SourceDocumentSummary:
    return SourceDocumentSummary(
        document_id=_safe_str(raw.get("document_id") or raw.get("id")),
        document_type=_safe_str(raw.get("document_type") or raw.get("type")),
        material=_safe_str(raw.get("material") or raw.get("biomaterial") or "mixed"),
        title=_safe_str(raw.get("title") or raw.get("document")),
        main_conclusion=_safe_str(raw.get("main_conclusion")),
        priority=_norm_priority(raw.get("priority") or "low"),
    )


def _documents_from_aggregate_matrix(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Строки document_matrix из aggregate_clinical → форма для SourceDocumentSummary."""
    agg = result.get("aggregate_clinical") if isinstance(result.get("aggregate_clinical"), dict) else {}
    matrix = agg.get("document_matrix") if isinstance(agg.get("document_matrix"), list) else []
    out: list[dict[str, Any]] = []
    for i, row in enumerate(matrix):
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "document_id": _safe_str(row.get("document_id")) or f"doc_{i + 1}",
                "document_type": _safe_str(row.get("document_type") or row.get("type")) or "generic_lab_document",
                "material": _safe_str(row.get("material") or row.get("biomaterial") or "mixed"),
                "title": _safe_str(row.get("title") or row.get("document") or row.get("name")),
                "main_conclusion": _safe_str(row.get("main_conclusion")),
                "priority": row.get("priority") or "low",
            }
        )
    return out


def _synthetic_risk_from_aggregate_or_display(result: dict[str, Any]) -> dict[str, Any] | None:
    """Если блок risk пуст, подставляем краткий вывод из aggregate_clinical или display_summary."""
    if (result.get("pattern_main_conclusion") or "").strip():
        # Не подменяем риск сырым aggregate/display — источник истины: pattern-driven summary.
        return None
    agg = result.get("aggregate_clinical") if isinstance(result.get("aggregate_clinical"), dict) else {}
    mc = agg.get("main_conclusion") if isinstance(agg.get("main_conclusion"), dict) else {}
    mp = _safe_str(mc.get("main_priority"))
    if mp:
        return {
            "domain": "aggregate",
            "level": "moderate",
            "score": 0.0,
            "label": "Главный клинический приоритет",
            "summary": mp,
            "patient_visible": True,
        }
    ds = _safe_str(result.get("display_summary"))
    if ds:
        return {
            "domain": "aggregate",
            "level": "low",
            "score": 0.0,
            "label": "Краткая сводка",
            "summary": ds[:2000],
            "patient_visible": True,
        }
    return None


def adapt_current_pipeline_result_to_core(result: dict[str, Any]) -> ClinicalCoreResult:
    normalized_values_raw = result.get("normalized_values") or {}
    normalized_values = {
        code: _to_lab_value(code, raw if isinstance(raw, dict) else {"value_text": raw})
        for code, raw in normalized_values_raw.items()
    }

    findings_raw = result.get("final_findings") or result.get("findings") or []
    if findings_raw and isinstance(findings_raw[0], str):
        # comment не дублируем title — иначе UI даёт строки вида «X — X»
        findings_raw = [
            {"title": x, "group": "Клиническая находка", "severity": "moderate", "comment": ""}
            for x in findings_raw
        ]

    hypotheses_raw = result.get("working_hypotheses") or result.get("hypotheses") or []
    if hypotheses_raw and isinstance(hypotheses_raw[0], str):
        hypotheses_raw = [{"label": x, "confidence": 1.0} for x in hypotheses_raw]

    next_steps_raw = result.get("next_steps") or []
    if not next_steps_raw and result.get("diagnostics"):
        next_steps_raw = [{"domain": "Диагностика", "what": x, "why": "", "priority": "medium"} for x in (result.get("diagnostics") or [])]

    indices_raw = result.get("derived_indices") or []
    risks_raw = list(result.get("risk") or [])
    if not risks_raw:
        syn = _synthetic_risk_from_aggregate_or_display(result)
        if syn:
            risks_raw = [syn]

    documents_raw = result.get("documents") or result.get("analyses") or []
    if not documents_raw:
        documents_raw = _documents_from_aggregate_matrix(result)
    if documents_raw and isinstance(documents_raw[0], dict) and "name" in documents_raw[0]:
        documents_raw = [
            {
                "document_id": f"doc_{i+1}",
                "document_type": d.get("document_type") or d.get("type") or "generic_lab_document",
                "material": d.get("material") or d.get("biomaterial") or "mixed",
                "title": d.get("name"),
                "main_conclusion": d.get("main_conclusion") or "",
                "priority": d.get("priority") or "low",
            }
            for i, d in enumerate(documents_raw)
        ]

    return ClinicalCoreResult(
        material=_safe_str(result.get("material") or "unknown"),
        material_confidence=float(result.get("material_confidence", 0.0)),
        document_type=_safe_str(result.get("document_type") or result.get("profile") or "unknown"),
        profile=_safe_str(result.get("profile") or result.get("document_type") or "unknown"),
        summary_level=_safe_str(result.get("summary_level") or "single_document"),
        normalized_values=normalized_values,
        documents=[_to_source_document(x) for x in documents_raw if isinstance(x, dict)],
        final_findings=[_to_finding(x) for x in findings_raw if isinstance(x, dict)],
        group_interpretations=list(result.get("group_interpretations") or []),
        working_hypotheses=[_to_hypothesis(x) for x in hypotheses_raw if isinstance(x, dict)],
        next_steps=[_to_next_step(x) for x in next_steps_raw if isinstance(x, dict)],
        derived_indices=[_to_index(x) for x in indices_raw if isinstance(x, dict)],
        risk=[_to_risk(x) for x in risks_raw if isinstance(x, dict)],
        limitations=list(result.get("limitations") or []),
        urgency=list(result.get("urgency") or [result.get("when_urgent")] if result.get("when_urgent") else []),
        pattern_summary_headline=_safe_str(result.get("pattern_summary_headline") or ""),
        pattern_main_conclusion=_safe_str(result.get("pattern_main_conclusion") or ""),
        pattern_attention_items=[str(x).strip() for x in (result.get("pattern_attention_items") or []) if str(x).strip()],
        pattern_next_steps_items=[str(x).strip() for x in (result.get("pattern_next_steps_items") or []) if str(x).strip()],
    )
