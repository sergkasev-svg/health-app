"""
Маршрут для документов organic_acids_urine.
Направляет в отдельный parser + formatter, не использует общий CBC/thyroid/lipids.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.parsers.organic_acids_parser import parse_organic_acids
from app.services.reports.organic_acids_physician_formatter import format_organic_acids_physician_report
from app.services.pretty_physician_report_tables import build_physician_report_html
from app.services.unified_report_presenter import build_unified_organic_acids_report
from app.services.filters.organic_acids_hypothesis_filter import (
    filter_organic_acids_hypotheses,
    FORBIDDEN_WITHOUT_SYMPTOM_SUPPORT,
)
from app.services.treatment_plan_generator import (
    extract_markers_from_report,
    generate_plan,
    generate_cta,
)
from app.services.lab_patient_demographics import enrich_report_with_patient_demographics

# Синхронно с app.services.report (без импорта report — цикл импортов)
_DISCLAIMER_TEXT = "Информация носит справочный характер и не заменяет консультацию врача."
_METABOLIC_EDU_DISCLAIMER = "Информация носит образовательный характер и не заменяет консультацию врача."

ORGANIC_ACIDS_PHRASES = (
    "органические кислоты в моче",
    "гх-мс",
    "organic_acids_urine",
    "маркеры углеводного обмена",
    "маркеры метаболизма",
)


def filename_suggests_organic_acids(filename: str) -> bool:
    """
    Имя файла часто единственный явный признак (OCR даёт «мочу»/ОАМ по шапке).
    Примеры: «…оргкислоты.pdf», «organic_acids.pdf», «ГХ-МС».
    """
    raw = (filename or "").strip()
    if not raw:
        return False
    low = raw.lower().replace(" ", "")
    needles = (
        "оргкислот",
        "органическ",
        "organicacid",
        "organic_acid",
        "oaprofile",
        "gh-ms",
        "ghms",
        "гх-мс",
        "гхмс",
        "orgacid",
    )
    return any(n in low for n in needles)


def route_organic_acids(text: str) -> bool:
    """Проверяет, является ли документ отчётом органических кислот."""
    low = (text or "").lower()
    if any(p in low for p in ORGANIC_ACIDS_PHRASES):
        return True
    # Бланк без явной шапки (OCR): типичные метаболиты + кислота и/или числовые значения
    metabolite_hints = (
        "миндальн",
        "ксантурен",
        "орот",
        "лимонн",
        "цитрат",
        "пируват",
        "ммоль/моль",
    )
    if any(h in low for h in metabolite_hints):
        has_numbers = bool(re.search(r"\d+[,.]\d+", low))
        if "кислот" in low or has_numbers or "0," in low or "0." in low:
            return True
    return False


def _apply_oa_patient_and_integrated_conclusion(
    report: Dict[str, Any],
    extracted: str,
    profile: Optional[Dict[str, Any]],
) -> None:
    """
    Демография с бланка (пол/возраст/даты) + интегрированный текст для шапки HTML,
    как у остальных лабораторных отчётов (pattern_main_conclusion).
    """
    enrich_report_with_patient_demographics(report, extracted, profile)
    if not (report.get("pattern_main_conclusion") or "").strip():
        pn = report.get("pattern_narrative") or []
        if isinstance(pn, list) and pn:
            report["pattern_main_conclusion"] = "\n".join(
                str(x).strip() for x in pn if str(x).strip()
            )
        elif isinstance(pn, str) and pn.strip():
            report["pattern_main_conclusion"] = pn.strip()
    if not (report.get("pattern_summary_headline") or "").strip() and (
        report.get("pattern_main_conclusion") or ""
    ).strip():
        report["pattern_summary_headline"] = "Клинический вывод по профилю органических кислот"


def _merge_treatment_plan_into_followup(report: Dict[str, Any]) -> None:
    """Добавляет строки из generate_plan в «Что проверить / рекомендации» для PDF."""
    plan = report.get("treatment_plan") or {}
    if not isinstance(plan, dict):
        return
    follow = list(report.get("recommended_followup_table") or [])
    seen = {str(r.get("check") or "").strip().lower() for r in follow if isinstance(r, dict)}
    buckets = (
        ("tests", "Дообследование", "По сигналам профиля; обсудить с врачом"),
        ("core_actions", "Клинический фокус", "Приоритетные направления"),
        ("supplements", "Нутриенты", "Не назначение; только по согласованию с врачом"),
        ("nutrition", "Питание", "Лайфстайл"),
        ("lifestyle", "Образ жизни", ""),
    )
    for key, direction, why in buckets:
        for item in (plan.get(key) or [])[:8]:
            s = str(item).strip()
            if not s:
                continue
            k = s.lower()
            if k in seen:
                continue
            seen.add(k)
            follow.append(
                {
                    "direction": direction,
                    "check": s,
                    "why": why or "Дополнение к плану по маркерам",
                    "priority": "Средний",
                }
            )
    report["recommended_followup_table"] = follow[:24]


def _profile_lines_for_oa(
    profile: Optional[Dict[str, Any]],
    report: Dict[str, Any],
) -> tuple[list[str], list[str]]:
    try:
        from app.services.report import _profile_clinical_context

        lp = report.get("patient") if isinstance(report.get("patient"), dict) else {}
        ctx = _profile_clinical_context(profile, lab_patient=lp)
        return ctx["profile_lines"], ctx["caution_lines"]
    except Exception:
        return [], []


def build_organic_acids_report(
    doc: Dict[str, Any],
    profile: Optional[Dict[str, Any]] = None,
    raw_hypotheses: Optional[list] = None,
) -> Dict[str, Any]:
    """
    Строит полный physician report для organic acids.
    Возвращает структурированный report с таблицами + HTML.
    Формат совместим с build_lab_report_from_doc (professional_summary, display_summary, user_summary).
    """
    extracted = (doc.get("extracted_text") or "").strip()
    fn = (doc.get("filename") or "").strip()
    text_ok = route_organic_acids(extracted)
    name_ok = filename_suggests_organic_acids(fn)
    if not extracted or not (text_ok or name_ok):
        return {}

    parsed = parse_organic_acids(
        text=extracted,
        filename=doc.get("filename") or "",
        profile=profile,
    )

    report = format_organic_acids_physician_report(
        parsed=parsed,
        raw_hypotheses=raw_hypotheses,
    )

    _validate_organic_acids_report(report)

    markers = extract_markers_from_report(report)
    treatment_plan = generate_plan(markers)
    report["treatment_plan"] = treatment_plan
    report["treatment_plan_cta"] = generate_cta(treatment_plan)

    _apply_oa_patient_and_integrated_conclusion(report, extracted, profile)
    _merge_treatment_plan_into_followup(report)

    report["physician_report_html"] = build_physician_report_html(report)
    # Plain text отдельно от HTML (избегаем циклического импорта на уровне модуля)
    from app.services.document_physician_report import _build_plain_text_report

    report["professional_summary"] = _build_plain_text_report(report)

    prof_lines, cav_lines = _profile_lines_for_oa(profile, report)
    unified = build_unified_organic_acids_report(
        doc=doc,
        doc_physician=report,
        profile_lines=prof_lines,
        caution_lines=cav_lines,
        compact_for_doctor=False,
        disclaimer_text=_DISCLAIMER_TEXT,
        educational_disclaimer=_METABOLIC_EDU_DISCLAIMER,
    )
    for k in (
        "display_summary",
        "user_summary",
        "user_report_text",
        "user_report_structured",
        "case_summary",
        "safe_next_steps",
        "when_urgent",
    ):
        if k in unified:
            report[k] = unified[k]

    report["document_type"] = "organic_acids_urine"
    report["document_name"] = doc.get("filename") or "документ"
    # patient + document_summary уже заполнены enrich_report_with_patient_demographics
    ds = dict(report.get("document_summary") or {})
    pat = dict(report.get("patient") or {})
    for k in ("sex", "age_years", "birth_year", "sample_type", "collection_date", "report_date"):
        v = pat.get(k)
        if v is None or str(v).strip() in ("", "—"):
            v2 = ds.get(k)
            if v2 is not None and str(v2).strip() not in ("", "—"):
                pat[k] = v2
    report["patient"] = pat
    report["sex"] = pat.get("sex")
    report["age"] = pat.get("age_years")

    return report


def _validate_organic_acids_report(report: Dict[str, Any]) -> None:
    """
    Validation rules: remove forbidden hypotheses, strip user-facing phrases,
    ensure abnormal table consistency.
    """
    # 1. Re-filter hypotheses: remove any forbidden that slipped through
    hypos = report.get("top_hypotheses_table") or []
    filtered_hypos: List[Dict[str, Any]] = []
    for h in hypos:
        text = (h.get("hypothesis") if isinstance(h, dict) else h) or ""
        low = str(text).lower()
        if any(f in low for f in FORBIDDEN_WITHOUT_SYMPTOM_SUPPORT):
            continue
        filtered_hypos.append(h)
    report["top_hypotheses_table"] = filtered_hypos[:5]

    # 2. Re-filter summary lines
    summary = report.get("summary") or []
    clean_summary: List[str] = []
    for s in summary:
        low = str(s).lower()
        if any(f in low for f in FORBIDDEN_WITHOUT_SYMPTOM_SUPPORT):
            continue
        clean_summary.append(s)
    report["summary"] = clean_summary[:5] if clean_summary else report.get("summary", [])
