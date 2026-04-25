"""
Unified JSON contract for clinical backend -> frontend.
Single payload that includes:
- core: canonical medical source of truth
- ui: ready-to-render screen blocks
- documents: physician/patient/aggregate rendered documents
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.services.clinical_engine.contracts import ClinicalCoreResult
from app.services.marker_table_filters import is_junk_marker_narrative as _is_junk_marker_narrative


class PatientBlock(BaseModel):
    display_name: Optional[str] = None
    sex: Optional[str] = None
    age: Optional[int] = None


class CoreDocumentItem(BaseModel):
    document_id: str = ""
    document_type: str = ""
    material: str = "mixed"
    title: str = ""
    main_conclusion: str = ""
    priority: str = "medium"


class CoreFinalFindingItem(BaseModel):
    code: str = ""
    title: str = ""
    group: str = ""
    severity: str = "info"
    document_id: Optional[str] = None
    primary_marker: Optional[str] = None
    value: Optional[str] = None
    reference: Optional[str] = None
    comment: str = ""
    patient_visible: bool = True
    physician_visible: bool = True


class CoreWorkingHypothesisItem(BaseModel):
    code: str = ""
    label: str = ""
    confidence: float = 1.0
    document_id: Optional[str] = None
    patient_visible: bool = False
    physician_visible: bool = True
    requires_confirmation: bool = False


class CoreNextStepItem(BaseModel):
    domain: str = "general"
    what: str = ""
    why: str = ""
    priority: str = "medium"
    patient_visible: bool = True
    physician_visible: bool = True


class CoreDerivedIndexItem(BaseModel):
    code: str = ""
    title: str = ""
    value: Optional[float] = None
    unit: str = ""
    status: str = "supportive"
    interpretation: str = ""
    confidence: str = "supportive"
    patient_visible: bool = True
    physician_visible: bool = True


class CoreRiskItem(BaseModel):
    domain: str = "general"
    level: str = "low"
    score: float = 0.0
    label: str = ""
    drivers: List[str] = Field(default_factory=list)
    summary: str = ""
    patient_visible: bool = True
    physician_visible: bool = True


class CoreBlock(BaseModel):
    material: str = "mixed"
    profile: str = "aggregate"
    summary_level: str = "multi_document"
    documents: List[CoreDocumentItem] = Field(default_factory=list)
    final_findings: List[CoreFinalFindingItem] = Field(default_factory=list)
    working_hypotheses: List[CoreWorkingHypothesisItem] = Field(default_factory=list)
    next_steps: List[CoreNextStepItem] = Field(default_factory=list)
    derived_indices: List[CoreDerivedIndexItem] = Field(default_factory=list)
    risk: List[CoreRiskItem] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    urgency: List[str] = Field(default_factory=list)


class UISummaryBlock(BaseModel):
    title: str = "🧾 Сводный отчёт"
    headline: str = ""
    subtext: str = ""
    risk_level: str = "low"


class UIAnalysisItem(BaseModel):
    name: str = ""
    priority: str = "low"
    badge_text: str = "Норма"


class UIIndexItem(BaseModel):
    label: str = ""
    value: str = ""
    comment: str = ""


class UIBlock(BaseModel):
    summary: UISummaryBlock = Field(default_factory=UISummaryBlock)
    analyses: List[UIAnalysisItem] = Field(default_factory=list)
    attention: List[str] = Field(default_factory=list)
    actions: List[str] = Field(default_factory=list)
    not_found: List[str] = Field(default_factory=list)
    indices: List[UIIndexItem] = Field(default_factory=list)
    physician_note: str = ""
    badges: List[str] = Field(default_factory=list)


class ReportSection(BaseModel):
    type: str = "text"  # text | list | table
    title: str = ""
    content: str = ""
    items: List[str] = Field(default_factory=list)
    columns: List[str] = Field(default_factory=list)
    rows: List[List[str]] = Field(default_factory=list)


class PhysicianReportDoc(BaseModel):
    title: str = "Отчёт для врача"
    subtitle: str = ""
    sections: List[ReportSection] = Field(default_factory=list)


class PatientReportDoc(BaseModel):
    title: str = "Понятный отчёт"
    sections: List[ReportSection] = Field(default_factory=list)


class AggregateReportDoc(BaseModel):
    title: str = "Сводный клинический отчёт"
    sections: List[ReportSection] = Field(default_factory=list)


class DocumentsBlock(BaseModel):
    physician_report: PhysicianReportDoc = Field(default_factory=PhysicianReportDoc)
    patient_report: PatientReportDoc = Field(default_factory=PatientReportDoc)
    aggregate_report: AggregateReportDoc = Field(default_factory=AggregateReportDoc)


class UnifiedClinicalPayload(BaseModel):
    report_id: str
    report_type: str = "aggregate_clinical_report"
    generated_at: str
    patient: PatientBlock = Field(default_factory=PatientBlock)
    core: CoreBlock = Field(default_factory=CoreBlock)
    ui: UIBlock = Field(default_factory=UIBlock)
    documents: DocumentsBlock = Field(default_factory=DocumentsBlock)
    # Полный лабораторный HTML для врача (скачивание PDF) — предпочтительнее секций-контракта
    physician_report_html_full: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _priority_to_level(priority: str) -> str:
    p = str(priority or "").lower()
    if "выс" in p or "high" in p:
        return "high"
    if "низ" in p or "low" in p:
        return "low"
    return "medium"


def _priority_badge(priority: str) -> str:
    level = _priority_to_level(priority)
    if level == "high":
        return "Высокий"
    if level == "medium":
        return "Контроль"
    return "Норма"


def _risk_level_from_priorities(priorities: List[str]) -> str:
    lvls = {_priority_to_level(x) for x in priorities}
    if "high" in lvls:
        return "high"
    if "medium" in lvls:
        return "medium"
    return "low"


def _float_or_none(raw: Any) -> Optional[float]:
    try:
        if raw is None or raw == "":
            return None
        return float(raw)
    except (TypeError, ValueError):
        return None


def _dedup_non_empty(items: List[str], limit: int = 100) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
        if len(out) >= limit:
            break
    return out


def _merge_headline_subtext(headline: str, subtext: str) -> str:
    """Склеивает заголовок и развёрнутый текст без дубля первой фразы."""
    h = (headline or "").strip()
    s = (subtext or "").strip()
    if not s:
        return h
    if not h:
        return s
    hl = h.lower().rstrip(".")
    sl = s.lower()
    if sl.startswith(hl) or (len(h) < 240 and hl and hl in sl[: len(h) + 8]):
        return s
    if len(h) < 30 and sl.startswith(hl[: min(len(hl), 20)]):
        return s
    # Короткий UI-title («Два основных направления внимания») + развёрнутый текст с «Выявлены два…» — один смысл
    if len(s) > 100 and "направлен" in hl and (
        "выявлен" in sl[:400]
        or sl.strip().startswith("1.")
        or "основных направлен" in sl[:200]
    ):
        return s
    if len(h) < 120 and "клинический вывод" in hl and len(s) > 80:
        return s
    return h + "\n\n" + s


def _filter_attention_vs_main(attention: List[str], main_text: str) -> List[str]:
    """Убирает пункты «зон внимания», уже полностью отражённые в основном тексте."""
    if not (main_text or "").strip():
        return attention
    mt = (main_text or "").lower()
    out: List[str] = []
    for a in attention:
        s = str(a or "").strip()
        if not s:
            continue
        sl = s.lower()
        if len(s) > 30 and sl in mt:
            continue
        first = sl.split("\n")[0][:120] if sl else ""
        if first and len(first) > 20 and first in mt:
            continue
        out.append(s)
    return _dedup_non_empty(out, limit=16)


def serialize_clinical_core_to_ui(core: ClinicalCoreResult, title: str = "🧾 Клинический отчёт") -> UIBlock:
    patterns = list(getattr(core, "clinical_patterns", None) or [])
    has_p1_patterns = any(getattr(p, "level", None) == "P1" for p in patterns)
    pm = (getattr(core, "pattern_main_conclusion", None) or "").strip()
    ph = (getattr(core, "pattern_summary_headline", None) or "").strip()
    pat_att = [str(x).strip() for x in (getattr(core, "pattern_attention_items", None) or []) if str(x).strip()]
    pat_ns = [str(x).strip() for x in (getattr(core, "pattern_next_steps_items", None) or []) if str(x).strip()]

    finding_lines = [
        str(f.title or f.summary_text).strip() for f in (core.final_findings or []) if str(f.title or f.summary_text).strip()
    ]
    if has_p1_patterns:
        finding_lines = []

    if pat_att:
        attention_lines = pat_att[:8]
    elif has_p1_patterns:
        attention_lines = [
            (getattr(p, "label", None) or "").strip()
            for p in patterns
            if getattr(p, "level", None) == "P1" and (getattr(p, "label", None) or "").strip()
        ][:8]
    else:
        attention_lines = finding_lines[:8]

    next_steps = [
        str(s.what if hasattr(s, "what") else (s.get("what") or s.get("check") or "")).strip()
        for s in (core.next_steps_structured or core.next_steps or [])
    ]
    next_steps = [x for x in next_steps if x]
    if pat_ns:
        next_steps = pat_ns[:10]

    indices = []
    for idx in (core.derived_indices or []):
        if not isinstance(idx, dict):
            continue
        indices.append(
            UIIndexItem(
                label=str(idx.get("name") or idx.get("code") or "Индекс"),
                value=str(idx.get("value") or "—"),
                comment=str(idx.get("interpretation") or ""),
            )
        )
    risk_level = "low"
    if core.risk and str(core.risk.overall_level or "").lower() in ("urgent", "high", "moderate", "medium", "low"):
        lv = str(core.risk.overall_level or "").lower()
        risk_level = "high" if lv in ("urgent", "high") else "medium" if lv in ("moderate", "medium") else "low"

    if pm:
        headline = ph or "Клинический вывод"
        if len(headline) > 180:
            headline = headline[:177] + "…"
        subtext = pm
    else:
        headline = str(core.summary or "")
        subtext = "Оценка основана на клиническом ядре и требует очной интерпретации в контексте жалоб."

    return UIBlock(
        summary=UISummaryBlock(
            title=title,
            headline=headline,
            subtext=subtext,
            risk_level=risk_level,
        ),
        analyses=[],
        attention=attention_lines,
        actions=next_steps[:10],
        not_found=[],
        indices=indices[:8],
        physician_note="Полная клиническая интерпретация доступна во врачебной версии отчёта.",
        badges=[],
    )


def serialize_aggregate_report_to_unified_payload(
    report: Dict[str, Any],
    report_id: str = "",
    generated_at: Optional[str] = None,
) -> UnifiedClinicalPayload:
    rep = report or {}
    agg = rep.get("aggregate_clinical") if isinstance(rep.get("aggregate_clinical"), dict) else {}
    matrix = agg.get("document_matrix") if isinstance(agg.get("document_matrix"), list) else []
    priorities = [str(x.get("priority") or "") for x in matrix if isinstance(x, dict)]

    core_documents: List[CoreDocumentItem] = []
    for i, row in enumerate(matrix):
        if not isinstance(row, dict):
            continue
        core_documents.append(
            CoreDocumentItem(
                document_id=f"doc_{i + 1}",
                document_type=str(row.get("type") or row.get("document_type") or "generic_lab_document"),
                material=str(row.get("biomaterial") or "mixed"),
                title=str(row.get("document") or f"Документ {i + 1}"),
                main_conclusion=str(row.get("main_conclusion") or ""),
                priority=_priority_to_level(str(row.get("priority") or "")),
            )
        )

    core_findings: List[CoreFinalFindingItem] = []
    for i, text in enumerate(agg.get("attention_zones") or []):
        line = str(text or "").strip()
        if not line:
            continue
        core_findings.append(
            CoreFinalFindingItem(
                code=f"finding_{i + 1}",
                title=line,
                group="Сводный паттерн",
                severity="high" if i == 0 else "moderate",
                comment=line,
            )
        )

    core_hyp: List[CoreWorkingHypothesisItem] = []
    for i, text in enumerate(agg.get("working_hypotheses") or []):
        line = str(text or "").strip()
        if not line:
            continue
        core_hyp.append(
            CoreWorkingHypothesisItem(
                code=f"hyp_{i + 1}",
                label=line,
                confidence=0.8 if i == 0 else 0.65,
                patient_visible=False,
                physician_visible=True,
                requires_confirmation=True,
            )
        )

    grouped = agg.get("next_checks_grouped") if isinstance(agg.get("next_checks_grouped"), dict) else {}
    steps_src: List[tuple[str, str]] = []
    for x in grouped.get("high") or []:
        steps_src.append(("high", str(x)))
    for x in grouped.get("medium") or []:
        steps_src.append(("medium", str(x)))
    for x in grouped.get("optional") or []:
        steps_src.append(("low", str(x)))
    if not steps_src:
        for x in agg.get("next_checks") or []:
            steps_src.append(("medium", str(x)))
    core_steps = [
        CoreNextStepItem(domain="Клинический контроль", what=text.strip(), why="", priority=prio)
        for prio, text in steps_src
        if text.strip()
    ]
    dedup_steps = _dedup_non_empty([x.what for x in core_steps], limit=30)
    core_steps = [CoreNextStepItem(domain="Клинический контроль", what=x, why="", priority="medium", patient_visible=True, physician_visible=True) for x in dedup_steps]

    core_indices: List[CoreDerivedIndexItem] = []
    for idx in agg.get("derived_indices") or []:
        if not isinstance(idx, dict):
            continue
        code = str(idx.get("name") or "index").lower().replace(" ", "_")
        core_indices.append(
            CoreDerivedIndexItem(
                code=code,
                title=str(idx.get("name") or "Индекс"),
                value=_float_or_none(idx.get("value")),
                unit=str(idx.get("unit") or ""),
                status=str(idx.get("status") or "supportive"),
                interpretation=str(idx.get("interpretation") or ""),
                confidence="supportive",
                patient_visible=True if code in ("bmi", "кердо", "kerdo") else False if code in ("nlr", "sii", "siri") else True,
                physician_visible=True,
            )
        )

    risk_level = _risk_level_from_priorities(priorities)
    risk_label = (
        "Высокий кардиометаболический риск"
        if risk_level == "high"
        else "Умеренный клинический риск"
        if risk_level == "medium"
        else "Низкий клинический риск"
    )
    risk_drivers = [str(x.get("main_conclusion") or "").strip() for x in matrix[:2] if isinstance(x, dict)]
    core_risk = [
        CoreRiskItem(
            domain="cardiometabolic" if risk_level == "high" else "general",
            level=risk_level,
            score=7.0 if risk_level == "high" else 4.0 if risk_level == "medium" else 1.0,
            label=risk_label,
            drivers=[x for x in risk_drivers if x],
            summary=str(agg.get("main_conclusion", {}).get("main_priority") or rep.get("display_summary") or ""),
        )
    ]

    ui_analyses = [
        UIAnalysisItem(
            name=str(row.get("document") or "Анализ"),
            priority=_priority_to_level(str(row.get("priority") or "")),
            badge_text=_priority_badge(str(row.get("priority") or "")),
        )
        for row in matrix
        if isinstance(row, dict)
    ]
    ui_indices = [
        UIIndexItem(
            label=str(idx.get("name") or "Индекс"),
            value=str(idx.get("value") or "—"),
            comment=str(idx.get("interpretation") or ""),
        )
        for idx in (agg.get("derived_indices") or [])
        if isinstance(idx, dict)
    ]
    main = agg.get("main_conclusion") if isinstance(agg.get("main_conclusion"), dict) else {}
    sec = [str(x).strip() for x in (main.get("secondary_findings") or []) if str(x).strip()]
    ui = UIBlock(
        summary=UISummaryBlock(
            title=str(agg.get("title") or "🧾 Сводный отчёт"),
            headline=str(main.get("main_priority") or rep.get("display_summary") or ""),
            subtext="; ".join(sec[:2]) if sec else "Остальные анализы без значимых отклонений.",
            risk_level=risk_level,
        ),
        analyses=ui_analyses,
        attention=[str(x).strip() for x in (agg.get("attention_zones") or []) if str(x).strip()][:12],
        actions=_dedup_non_empty([x.what for x in core_steps if x.patient_visible], limit=12),
        not_found=[str(x).strip() for x in (agg.get("not_supported") or []) if str(x).strip()][:10],
        indices=ui_indices[:10],
        physician_note="Полная клиническая интерпретация, гипотезы и расчёты доступны во врачебной версии отчёта.",
        badges=[],
    )

    pm_agg = str(rep.get("pattern_main_conclusion") or "").strip()
    ph_agg = str(rep.get("pattern_summary_headline") or "").strip()
    merged_patterns = rep.get("clinical_patterns_merged") if isinstance(rep.get("clinical_patterns_merged"), list) else []
    if pm_agg:
        h_line = ph_agg[:180] + ("…" if len(ph_agg) > 180 else "") if ph_agg else "Клинический интегрированный вывод"
        ui = ui.model_copy(
            update={
                "summary": ui.summary.model_copy(update={"headline": h_line, "subtext": pm_agg}),
                "attention": _filter_attention_vs_main(list(ui.attention), pm_agg),
            }
        )
    else:
        ui = ui.model_copy(
            update={
                "attention": _filter_attention_vs_main(
                    list(ui.attention),
                    _merge_headline_subtext(ui.summary.headline, ui.summary.subtext),
                )
            }
        )

    physician_sections = []
    physician_brief = str(rep.get("professional_summary") or rep.get("display_summary") or "").strip()
    if pm_agg:
        physician_sections.append(
            ReportSection(
                type="text",
                title="Интегрированный клинический вывод (P1/P2)",
                content=pm_agg,
            )
        )
    if merged_patterns:
        pat_rows: List[List[str]] = []
        for p in merged_patterns[:16]:
            if not isinstance(p, dict):
                continue
            pat_rows.append(
                [
                    str(p.get("label") or "—"),
                    str(p.get("level") or "—"),
                    (str(p.get("rationale") or "")[:420] + ("…" if len(str(p.get("rationale") or "")) > 420 else "")),
                ]
            )
        if pat_rows:
            physician_sections.append(
                ReportSection(
                    type="table",
                    title="Выявленные клинические паттерны",
                    columns=["Паттерн", "Уровень", "Обоснование (фрагмент)"],
                    rows=pat_rows,
                )
            )
    if physician_brief:
        physician_sections.append(ReportSection(type="text", title="Развёрнутая сводка для врача", content=physician_brief))
    matrix_rows = [
        [
            str(row.get("document") or "—"),
            str(row.get("main_conclusion") or "—"),
            _priority_badge(str(row.get("priority") or "")),
        ]
        for row in matrix
        if isinstance(row, dict)
    ]
    if matrix_rows:
        physician_sections.append(
            ReportSection(
                type="table",
                title="Сводка по анализам",
                columns=["Анализ", "Краткий вывод", "Приоритет"],
                rows=matrix_rows,
            )
        )
    doc_sections = rep.get("aggregate_document_sections") if isinstance(rep.get("aggregate_document_sections"), list) else []
    for i, ds in enumerate(doc_sections, start=1):
        if not isinstance(ds, dict):
            continue
        marker_rows_raw = ds.get("key_marker_rows") if isinstance(ds.get("key_marker_rows"), list) else []
        marker_rows = []
        for mr in marker_rows_raw:
            if not isinstance(mr, dict):
                continue
            mk = str(mr.get("marker") or "").strip()
            if _is_junk_marker_narrative(mk, str(mr.get("comment") or "")):
                continue
            marker_rows.append(
                [
                    str(mr.get("marker") or "Показатель"),
                    str(mr.get("value") or "—"),
                    str(mr.get("reference") or "—"),
                    str(mr.get("comment") or "—"),
                ]
            )
        if not marker_rows:
            continue
        doc_label = str(ds.get("analysis_type_label_ru") or ds.get("filename") or f"Документ {i}")
        physician_sections.append(
            ReportSection(
                type="table",
                title=f"Ключевые отклонения — {doc_label}",
                columns=["Показатель", "Результат", "Референс", "Комментарий"],
                rows=marker_rows[:12],
            )
        )
    if ui.attention:
        physician_sections.append(ReportSection(type="list", title="Зоны внимания", items=ui.attention[:12]))
    if ui.not_found:
        physician_sections.append(ReportSection(type="list", title="Что по этим данным не подтверждается", items=ui.not_found[:12]))
    if ui.indices:
        physician_sections.append(
            ReportSection(
                type="table",
                title="Интегральные и расчётные индексы",
                columns=["Индекс", "Значение", "Комментарий"],
                rows=[[str(x.label), str(x.value), str(x.comment or "")] for x in ui.indices[:12]],
            )
        )
    if core_hyp:
        physician_sections.append(
            ReportSection(
                type="list",
                title="Рабочие гипотезы (не диагнозы)",
                items=[x.label for x in core_hyp[:10]],
            )
        )
    grouped_high = _dedup_non_empty([str(x).strip() for x in (grouped.get("high") or [])], limit=12)
    grouped_medium = _dedup_non_empty([str(x).strip() for x in (grouped.get("medium") or [])], limit=12)
    grouped_optional = _dedup_non_empty([str(x).strip() for x in (grouped.get("optional") or [])], limit=12)
    if grouped_high:
        physician_sections.append(ReportSection(type="list", title="Что проверить дальше — высокий приоритет", items=grouped_high))
    if grouped_medium:
        physician_sections.append(ReportSection(type="list", title="Что проверить дальше — средний приоритет", items=grouped_medium))
    if grouped_optional:
        physician_sections.append(ReportSection(type="list", title="Что проверить дальше — по показаниям", items=grouped_optional))
    strategy_lines = _dedup_non_empty([str(x).strip() for x in (agg.get("strategy") or [])], limit=8)
    limitations_lines = _dedup_non_empty([str(x).strip() for x in (agg.get("limitations") or [])], limit=8)
    urgent_line = str(agg.get("urgent") or rep.get("when_urgent") or "").strip()
    if strategy_lines:
        physician_sections.append(ReportSection(type="list", title="Общая стратегия", items=strategy_lines))
    if limitations_lines:
        physician_sections.append(ReportSection(type="list", title="Ограничения интерпретации", items=limitations_lines))
    if urgent_line:
        physician_sections.append(ReportSection(type="text", title="Когда срочно", content=urgent_line))

    patient_sections = []
    patient_main = str(rep.get("user_summary") or ui.summary.headline or "").strip()
    if patient_main:
        patient_sections.append(ReportSection(type="text", title="Что главное", content=patient_main))
    if ui.attention:
        patient_sections.append(ReportSection(type="list", title="Что по анализам требует внимания", items=ui.attention[:8]))
    patient_actions = _dedup_non_empty(ui.actions, limit=12)
    if patient_actions:
        patient_sections.append(ReportSection(type="list", title="Что сделать дальше", items=patient_actions))
    if ui.not_found:
        patient_sections.append(ReportSection(type="list", title="Что не выявлено", items=ui.not_found[:8]))
    patient_indices_rows = [
        [str(x.label), str(x.value), str(x.comment or "")]
        for x in ui.indices
        if str(x.label or "").strip().lower() in ("имт", "bmi")
    ]
    if patient_indices_rows:
        patient_sections.append(
            ReportSection(
                type="table",
                title="Поддерживающие индексы",
                columns=["Индекс", "Значение", "Комментарий"],
                rows=patient_indices_rows,
            )
        )
    if urgent_line:
        patient_sections.append(ReportSection(type="text", title="Когда срочно", content=urgent_line))

    aggregate_sections = []
    main_body = _merge_headline_subtext(str(ui.summary.headline or "").strip(), str(ui.summary.subtext or "").strip())
    if main_body:
        aggregate_sections.append(ReportSection(type="text", title="Главный вывод", content=main_body))
    if matrix_rows:
        aggregate_sections.append(
            ReportSection(
                type="table",
                title="Сводка по анализам",
                columns=["Анализ", "Краткий вывод", "Приоритет"],
                rows=matrix_rows,
            )
        )
    if ui.attention:
        aggregate_sections.append(ReportSection(type="list", title="Зоны внимания", items=ui.attention[:12]))
    if ui.not_found:
        aggregate_sections.append(ReportSection(type="list", title="Что не подтверждается", items=ui.not_found[:12]))
    if ui.indices:
        aggregate_sections.append(
            ReportSection(
                type="table",
                title="Интегральные и расчётные индексы",
                columns=["Индекс", "Значение", "Комментарий"],
                rows=[[str(x.label), str(x.value), str(x.comment or "")] for x in ui.indices[:12]],
            )
        )
    if patient_actions:
        aggregate_sections.append(ReportSection(type="list", title="Что проверить дальше", items=patient_actions))
    if strategy_lines:
        aggregate_sections.append(ReportSection(type="list", title="Общая стратегия", items=strategy_lines))
    if limitations_lines:
        aggregate_sections.append(ReportSection(type="list", title="Ограничения интерпретации", items=limitations_lines))
    if urgent_line:
        aggregate_sections.append(ReportSection(type="text", title="Когда срочно", content=urgent_line))

    html_full = str(rep.get("physician_report_html") or "").strip()
    pat_block = rep.get("patient") if isinstance(rep.get("patient"), dict) else {}

    payload = UnifiedClinicalPayload(
        report_id=report_id or ("agg_" + datetime.now().strftime("%Y_%m_%d_%H%M%S")),
        report_type=str(rep.get("document_type") or "aggregate_clinical_report"),
        generated_at=generated_at or _now_iso(),
        physician_report_html_full=html_full,
        patient=PatientBlock(
            display_name=str(rep.get("patient_name") or pat_block.get("display_name") or "").strip() or None,
            sex=rep.get("sex") or pat_block.get("sex"),
            age=rep.get("age") if rep.get("age") is not None else pat_block.get("age_years") or pat_block.get("age"),
        ),
        core=CoreBlock(
            material="mixed",
            profile="aggregate",
            summary_level="multi_document",
            documents=core_documents,
            final_findings=core_findings,
            working_hypotheses=core_hyp,
            next_steps=core_steps,
            derived_indices=core_indices,
            risk=core_risk,
            limitations=[str(x).strip() for x in (agg.get("limitations") or []) if str(x).strip()],
            urgency=[str(agg.get("urgent") or rep.get("when_urgent") or "").strip()] if str(agg.get("urgent") or rep.get("when_urgent") or "").strip() else [],
        ),
        ui=ui,
        documents=DocumentsBlock(
            physician_report=PhysicianReportDoc(
                title="Отчёт для врача",
                subtitle=str(rep.get("display_summary") or ""),
                sections=physician_sections,
            ),
            patient_report=PatientReportDoc(
                title="Понятный отчёт",
                sections=patient_sections,
            ),
            aggregate_report=AggregateReportDoc(
                title=str(agg.get("title") or "Сводный клинический отчёт"),
                sections=aggregate_sections,
            ),
        ),
    )
    return payload

