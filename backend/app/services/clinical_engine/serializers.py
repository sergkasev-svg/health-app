from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable
from uuid import uuid4

from app.services.clinical_engine.unified_contract import _merge_headline_subtext
from app.services.clinical_engine.contracts_api import (
    AggregateClinicalReportPayload,
    ClinicalCoreResult,
    DocumentsPayload,
    Finding,
    NextStep,
    PatientInfo,
    RenderedDocument,
    RenderedSection,
    RiskAssessment,
    UIAnalysisItem,
    UIBlockPayload,
    UIIndexItem,
    UISummaryBlock,
)


SEVERITY_ORDER = {
    "urgent": 5,
    "high": 4,
    "moderate": 3,
    "mild": 2,
    "borderline": 1,
    "info": 0,
}


PRIORITY_BADGE_TEXT = {
    "high": "Высокий",
    "medium": "Контроль",
    "low": "Низкий",
    "urgent": "Срочно",
}


def _finding_attention_line(f: Finding) -> str:
    """Одна строка «зоны внимания»: без дубля «заголовок — тот же текст»."""
    title = (f.title or "").strip()
    comment = (f.comment or "").strip().rstrip(".")
    if not comment or comment.lower() == title.lower():
        return title
    return f"{title} — {comment}"


def _dedupe_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        item = (item or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _top_risk(risks: list[RiskAssessment]) -> RiskAssessment | None:
    if not risks:
        return None
    weight = {"urgent": 4, "high": 3, "moderate": 2, "low": 1}
    return sorted(risks, key=lambda r: (weight.get(r.level, 0), r.score), reverse=True)[0]


def _top_findings(findings: list[Finding], limit: int = 5) -> list[Finding]:
    return sorted(
        findings,
        key=lambda f: (SEVERITY_ORDER.get(f.severity, 0), f.confidence),
        reverse=True,
    )[:limit]


def _negative_summaries_from_groups(group_interpretations: list[dict]) -> list[str]:
    result: list[str] = []
    negative_markers = [
        "не выявлено",
        "не получено",
        "не подтверждается",
        "нет признаков",
        "не обнаружены",
    ]
    for group in group_interpretations:
        interpretation = str(group.get("interpretation", "")).strip()
        low = interpretation.lower()
        if any(m in low for m in negative_markers):
            result.append(interpretation.rstrip("."))
    return _dedupe_keep_order(result)


def build_ui_summary(core: ClinicalCoreResult) -> UISummaryBlock:
    top_risk = _top_risk(core.risk)
    risk_level = top_risk.level if top_risk else "low"
    # P1/P2: интегрированный вывод по паттернам (без сырых «Снижен LDL» и т.п.)
    pm = getattr(core, "pattern_main_conclusion", None) or ""
    if str(pm).strip():
        headline = getattr(core, "pattern_summary_headline", None) or "Клинический вывод"
        h = str(headline).strip()
        if len(h) > 180:
            h = h[:177] + "…"
        return UISummaryBlock(
            title="🧾 Сводный отчёт",
            headline=h,
            subtext=str(pm).strip(),
            risk_level=risk_level,
        )

    top_findings = _top_findings(core.final_findings, limit=2)
    if top_findings:
        headline = top_findings[0].title
        if len(top_findings) > 1:
            t1, t2 = top_findings[0].title.strip(), top_findings[1].title.strip()
            if t1.lower() != t2.lower():
                headline = f"{t1}; вторая по значимости: {t2}"
    else:
        headline = "Существенных клинически значимых отклонений не выявлено"
    if top_risk and top_risk.summary:
        subtext = top_risk.summary
    elif core.documents:
        secondary = [d.main_conclusion for d in core.documents[1:3] if d.main_conclusion]
        subtext = "; ".join(secondary) if secondary else "Остальные находки вторичны"
    else:
        subtext = "Сводная клиническая интерпретация готова"
    return UISummaryBlock(
        title="🧾 Сводный отчёт",
        headline=headline,
        subtext=subtext,
        risk_level=risk_level,
    )


def build_ui_analyses(core: ClinicalCoreResult) -> list[UIAnalysisItem]:
    return [
        UIAnalysisItem(
            name=doc.title,
            priority=doc.priority,
            badge_text=PRIORITY_BADGE_TEXT.get(doc.priority, "Низкий"),
        )
        for doc in core.documents
    ]


def build_ui_attention(core: ClinicalCoreResult) -> list[str]:
    pat_att = getattr(core, "pattern_attention_items", None) or []
    if pat_att:
        return _dedupe_keep_order([str(x).strip() for x in pat_att if str(x).strip()][:6])
    # Pattern-driven summary без списка зон — не показываем marker-level строки
    if (getattr(core, "pattern_main_conclusion", None) or "").strip():
        return []
    findings = [
        _finding_attention_line(f)
        for f in _top_findings(
            [f for f in core.final_findings if f.patient_visible],
            limit=6,
        )
        if f.severity in {"high", "moderate", "mild", "borderline"}
    ]
    return _dedupe_keep_order(findings[:5])


def build_ui_actions(core: ClinicalCoreResult) -> list[str]:
    pat_ns = getattr(core, "pattern_next_steps_items", None) or []
    if pat_ns:
        return _dedupe_keep_order([str(x).strip() for x in pat_ns if str(x).strip()][:8])
    ordered = sorted(
        [s for s in core.next_steps if s.patient_visible],
        key=lambda s: {"urgent": 0, "high": 1, "medium": 2, "low": 3}.get(s.priority, 9),
    )
    return _dedupe_keep_order([s.what for s in ordered][:6])


def build_ui_not_found(core: ClinicalCoreResult) -> list[str]:
    return _negative_summaries_from_groups(core.group_interpretations)[:6]


def build_ui_indices(core: ClinicalCoreResult) -> list[UIIndexItem]:
    items: list[UIIndexItem] = []
    for idx in core.derived_indices:
        if not idx.patient_visible:
            continue
        value = "не рассчитан" if idx.value is None else str(idx.value)
        items.append(UIIndexItem(label=idx.title, value=value, comment=idx.interpretation or ""))
    return items[:6]


def build_ui_payload(core: ClinicalCoreResult) -> UIBlockPayload:
    return UIBlockPayload(
        summary=build_ui_summary(core),
        analyses=build_ui_analyses(core),
        attention=build_ui_attention(core),
        actions=build_ui_actions(core),
        not_found=build_ui_not_found(core),
        indices=build_ui_indices(core),
        physician_note="Полная клиническая интерпретация, гипотезы и расчёты доступны во врачебной версии отчёта.",
    )


def render_physician_report(core: ClinicalCoreResult) -> RenderedDocument:
    sections: list[RenderedSection] = []
    top_risk = _top_risk(core.risk)
    if top_risk:
        sections.append(
            RenderedSection(
                type="text",
                title="Краткий вывод",
                content=top_risk.summary or top_risk.label,
            )
        )
    if core.final_findings:
        rows: list[list[str]] = []
        for f in core.final_findings:
            if not f.physician_visible:
                continue
            rows.append([f.title, f.value or "", f.reference or "", f.comment or ""])
        if rows:
            sections.append(
                RenderedSection(
                    type="table",
                    title="Ключевые отклонения",
                    columns=["Показатель", "Результат", "Референс", "Комментарий"],
                    rows=rows,
                )
            )
    if core.group_interpretations:
        rows2: list[list[str]] = []
        for g in core.group_interpretations:
            markers = g.get("supporting_markers", [])
            marker_str = ", ".join(markers) if isinstance(markers, list) else str(markers)
            rows2.append([str(g.get("group", "")), marker_str, str(g.get("interpretation", ""))])
        sections.append(
            RenderedSection(
                type="table",
                title="Клиническая интерпретация по группам",
                columns=["Группа", "Поддерживающие маркеры", "Интерпретация"],
                rows=rows2,
            )
        )
    hypotheses = [h.label for h in core.working_hypotheses if h.physician_visible]
    if hypotheses:
        sections.append(RenderedSection(type="list", title="Рабочие гипотезы", items=hypotheses))
    if core.next_steps:
        rows3 = [[s.domain, s.what, s.why, s.priority] for s in core.next_steps if s.physician_visible]
        sections.append(
            RenderedSection(
                type="table",
                title="Что проверить дальше",
                columns=["Направление", "Что проверить", "Зачем", "Приоритет"],
                rows=rows3,
            )
        )
    if core.derived_indices:
        rows4 = []
        for idx in core.derived_indices:
            if not idx.physician_visible:
                continue
            rows4.append([idx.title, "не рассчитан" if idx.value is None else str(idx.value), idx.status or "", idx.interpretation or ""])
        sections.append(
            RenderedSection(
                type="table",
                title="Интегральные и расчётные индексы",
                columns=["Индекс", "Значение", "Статус", "Интерпретация"],
                rows=rows4,
            )
        )
    if core.limitations:
        sections.append(RenderedSection(type="list", title="Ограничения интерпретации", items=core.limitations))
    if core.urgency:
        sections.append(RenderedSection(type="list", title="Когда срочно", items=core.urgency))
    return RenderedDocument(
        title="Отчёт для врача",
        subtitle="Структурированная клиническая интерпретация",
        sections=sections,
    )


def render_patient_report(core: ClinicalCoreResult) -> RenderedDocument:
    sections: list[RenderedSection] = []
    ui = build_ui_payload(core)
    sections.append(
        RenderedSection(
            type="text",
            title="Что главное",
            content=_merge_headline_subtext(str(ui.summary.headline or ""), str(ui.summary.subtext or "")),
        )
    )
    if ui.attention:
        sections.append(RenderedSection(type="list", title="Что требует внимания", items=ui.attention))
    if ui.actions:
        sections.append(RenderedSection(type="list", title="Что сделать дальше", items=ui.actions))
    if core.urgency:
        sections.append(RenderedSection(type="list", title="Когда не ждать", items=core.urgency))
    return RenderedDocument(
        title="Понятный отчёт",
        subtitle="Краткая интерпретация результатов",
        sections=sections,
    )


def render_aggregate_report(core: ClinicalCoreResult) -> RenderedDocument:
    sections: list[RenderedSection] = []
    ui = build_ui_payload(core)
    sections.append(
        RenderedSection(
            type="text",
            title="Главный вывод",
            content=_merge_headline_subtext(str(ui.summary.headline or ""), str(ui.summary.subtext or "")),
        )
    )
    if core.documents:
        rows = [[d.title, d.main_conclusion, d.priority] for d in core.documents]
        sections.append(
            RenderedSection(
                type="table",
                title="Сводка по анализам",
                columns=["Анализ", "Краткий вывод", "Приоритет"],
                rows=rows,
            )
        )
    if ui.attention:
        sections.append(RenderedSection(type="list", title="Зоны внимания", items=ui.attention))
    not_found = build_ui_not_found(core)
    if not_found:
        sections.append(RenderedSection(type="list", title="Что по этим данным не подтверждается", items=not_found))
    if ui.indices:
        sections.append(
            RenderedSection(
                type="list",
                title="Интегральные и расчётные индексы",
                items=[f"{i.label}: {i.value}" + (f" ({i.comment})" if i.comment else "") for i in ui.indices],
            )
        )
    if ui.actions:
        sections.append(RenderedSection(type="list", title="Что проверить дальше", items=ui.actions))
    return RenderedDocument(
        title="Сводный клинический отчёт",
        subtitle="Интеграция нескольких лабораторных исследований",
        sections=sections,
    )


def build_documents_payload(core: ClinicalCoreResult) -> DocumentsPayload:
    return DocumentsPayload(
        physician_report=render_physician_report(core),
        patient_report=render_patient_report(core),
        aggregate_report=render_aggregate_report(core),
    )


def build_aggregate_payload(
    core: ClinicalCoreResult,
    patient: PatientInfo | None = None,
    report_type: str = "aggregate_clinical_report",
    report_id: str | None = None,
    physician_report_html_full: str = "",
) -> AggregateClinicalReportPayload:
    patient = patient or PatientInfo()
    ui = build_ui_payload(core)
    documents = build_documents_payload(core)
    return AggregateClinicalReportPayload(
        report_id=report_id or f"report_{uuid4().hex[:12]}",
        report_type=report_type,
        generated_at=datetime.now(timezone.utc),
        patient=patient,
        core=core,
        ui=ui,
        documents=documents,
        physician_report_html_full=str(physician_report_html_full or "").strip(),
    )
