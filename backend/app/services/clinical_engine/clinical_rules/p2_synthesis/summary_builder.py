"""
Сборка главного вывода, зон внимания и шагов из P1/P2 паттернов.
Фильтрует технический мусор пайплайна; при наличии паттернов не опирается на сырые marker-level findings в UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional

from app.services.clinical_engine.contracts import ClinicalCoreResult, ClinicalPattern, Finding
from app.services.clinical_engine.clinical_rules.p2_synthesis.action_prioritizer import (
    prioritize_actions,
    prioritize_actions_from_patterns,
    prioritized_actions_to_strings,
)
from app.services.clinical_engine.clinical_rules.pediatric_adjustments import apply_pediatric_tone_to_summary

# =========================
# I/O models
# =========================


@dataclass
class SummaryBuildInput:
    clinical_patterns: List[ClinicalPattern] = field(default_factory=list)
    findings: List[Any] = field(default_factory=list)
    next_steps: List[Any] = field(default_factory=list)
    risks: List[Any] = field(default_factory=list)
    fallback_summary: str = ""
    is_pediatric: bool = False
    patient_meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class SummaryBuildOutput:
    main_conclusion: str
    ui_headline: str
    attention_items: List[str]
    next_steps_items: List[str]


# =========================
# Technical text filters
# =========================

FORBIDDEN_SUMMARY_PATTERNS = [
    "в одном файле объединены",
    "извлечённые из текста",
    "при наличии в бланке",
    "модуль системы",
    "ниже учтены",
    "дополнительно извлечённые",
    "в одном файле",
    "из текста показатели",
    "липидный модуль системы",
]

FORBIDDEN_UI_FINDING_PATTERNS = [
    "хороший уровень hdl",
    "снижен ldl",
    "ldl low",
    "good hdl",
    "хороший hdl",
]

SAFE_EMPTY_SUMMARY = "Существенных клинически значимых отклонений по совокупности данных не выявлено."


def _normalize_spaces(text: str) -> str:
    return " ".join((text or "").strip().split())


def _strip_trailing_punctuation(text: str) -> str:
    text = _normalize_spaces(text)
    while text.endswith(("..", " .", ";.", ",.")):
        text = text[:-1].rstrip()
    if text.endswith((";", ",")):
        text = text[:-1].rstrip()
    return text


def _ensure_sentence(text: str) -> str:
    text = _strip_trailing_punctuation(text)
    if not text:
        return ""
    if text[-1] not in ".!?":
        text += "."
    return text


def _is_technical_text(text: str) -> bool:
    low = _normalize_spaces(text).lower()
    return any(p in low for p in FORBIDDEN_SUMMARY_PATTERNS)


def _is_bad_ui_finding(text: str) -> bool:
    low = _normalize_spaces(text).lower()
    return any(p in low for p in FORBIDDEN_UI_FINDING_PATTERNS)


def _dedupe_keep_order(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for raw in items:
        item = _normalize_spaces(raw)
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _sort_patterns(patterns: List[ClinicalPattern]) -> List[ClinicalPattern]:
    """Совместимость: список уже отранжирован pattern_ranker — порядок сохраняем."""
    return list(patterns)


def _step_what(s: Any) -> str:
    if isinstance(s, dict):
        return str(s.get("what") or s.get("check") or "").strip()
    return str(getattr(s, "what", "") or getattr(s, "check", "") or "").strip()


def _step_priority(s: Any) -> str:
    if isinstance(s, dict):
        return str(s.get("priority") or "medium").lower()
    return str(getattr(s, "priority", "medium") or "medium").lower()


def _step_visible(s: Any) -> bool:
    pv = s.get("patient_visible") if isinstance(s, dict) else getattr(s, "patient_visible", True)
    ph = s.get("physician_visible") if isinstance(s, dict) else getattr(s, "physician_visible", True)
    if pv is False and ph is False:
        return False
    return True


def _sort_steps(steps: List[Any]) -> List[Any]:
    priority_rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(
        steps,
        key=lambda s: (priority_rank.get(_step_priority(s), 9), _step_what(s).lower()),
    )


def _finding_title(f: Any) -> str:
    if isinstance(f, Finding):
        return (f.title or "").strip()
    return str(getattr(f, "title", "") or "").strip()


def _finding_severity(f: Any) -> str:
    return str(getattr(f, "severity", "info") or "info").lower()


def _finding_patient_visible(f: Any) -> bool:
    v = getattr(f, "patient_visible", None)
    if v is False:
        return False
    return True


# =========================
# Core logic
# =========================


def _build_main_conclusion_from_patterns(
    patterns: List[ClinicalPattern],
    fallback_summary: str = "",
    patient_meta: Optional[dict[str, Any]] = None,
) -> tuple[str, str]:
    """Возвращает (main_conclusion, ui_headline)."""
    pm = dict(patient_meta or {})
    visible = [p for p in patterns if p.physician_visible]
    visible = _sort_patterns(visible)

    p1 = [p for p in visible if p.level == "P1"]
    p2 = [p for p in visible if p.level == "P2"]

    ui_headline = "Клинический вывод"

    if p1:
        primary = p1[:2]
        lines: List[str] = []

        if len(primary) == 1:
            p = primary[0]
            lines.append(f"{p.label} — {_strip_trailing_punctuation(p.rationale)}")
            ui_headline = p.label[:120] if p.label else ui_headline
        else:
            p_first, p_second = primary[0], primary[1]
            lines.append("Выявлены два основных направления:")
            lines.append(
                f"1. {p_first.label} — {_strip_trailing_punctuation(p_first.rationale)}"
            )
            lines.append(
                f"2. {p_second.label} — {_strip_trailing_punctuation(p_second.rationale)}"
            )
            ui_headline = "Два основных направления внимания"

        secondary_labels = [p.label for p in p2[:2] if p.label]
        if secondary_labels:
            lines.append("Дополнительно: " + ", ".join(_dedupe_keep_order(secondary_labels)).rstrip(".") + ".")

        if len(primary) == 1:
            result = " ".join(_dedupe_keep_order(lines))
            result = _ensure_sentence(result)
        else:
            result = "\n".join(lines).strip()
            if result and result[-1] not in ".!?":
                result += "."
        result = apply_pediatric_tone_to_summary(result, pm)
        return result, ui_headline

    if p2:
        labels = [p.label for p in p2[:3] if p.label]
        if labels:
            text = _ensure_sentence(
                "Выявлены дополнительные клинические сигналы: " + ", ".join(_dedupe_keep_order(labels))
            )
            text = apply_pediatric_tone_to_summary(text, pm)
            return text, "Дополнительные сигналы"

    fallback_summary = _normalize_spaces(fallback_summary)
    if fallback_summary and not _is_technical_text(fallback_summary):
        fb = _ensure_sentence(fallback_summary)
        fb = apply_pediatric_tone_to_summary(fb, pm)
        return fb, ui_headline

    return SAFE_EMPTY_SUMMARY, ui_headline


def _build_attention_items(patterns: List[ClinicalPattern], findings: List[Any]) -> List[str]:
    """
    Зоны внимания: при наличии P1-паттернов не откатываемся к marker-level findings
    («Снижен LDL», «Хороший HDL» и т.д.).
    """
    if any(p.level == "P1" for p in patterns):
        p1_labels = [
            (p.label or "").strip()
            for p in _sort_patterns(list(patterns))
            if p.level == "P1" and (p.label or "").strip()
        ][:6]
        if p1_labels:
            return _dedupe_keep_order(p1_labels)
        return []

    visible_patterns = [p for p in patterns if p.patient_visible]
    visible_patterns = _sort_patterns(visible_patterns)

    p1 = [p for p in visible_patterns if p.level == "P1"]
    p2 = [p for p in visible_patterns if p.level == "P2"]

    if p1:
        return _dedupe_keep_order([p.label for p in p1[:4]])

    if p2:
        return _dedupe_keep_order([p.label for p in p2[:4]])

    if patterns:
        return []

    severity_rank = {"urgent": 5, "high": 4, "moderate": 3, "mild": 2, "borderline": 1, "info": 0}
    visible_findings = [f for f in findings if _finding_patient_visible(f)]
    visible_findings.sort(key=lambda f: severity_rank.get(_finding_severity(f), 0), reverse=True)

    raw_items: List[str] = []
    for f in visible_findings:
        text = _finding_title(f)
        if not text:
            continue
        if _is_technical_text(text) or _is_bad_ui_finding(text):
            continue
        raw_items.append(text)

    return _dedupe_keep_order(raw_items[:4])


def _patient_age_int(patient_meta: dict[str, Any]) -> Optional[int]:
    a = patient_meta.get("age_years")
    if a is None:
        return None
    try:
        return int(float(a))
    except (TypeError, ValueError):
        return None


def _risks_list_from_meta_and_explicit(
    patient_meta: dict[str, Any],
    explicit: List[Any],
) -> List[Any]:
    if explicit:
        return list(explicit)
    r = patient_meta.get("risk_assessments") or patient_meta.get("risks")
    if isinstance(r, list):
        return list(r)
    return []


def _build_next_steps_combined(
    patterns: List[ClinicalPattern],
    steps: List[Any],
    patient_meta: dict[str, Any],
    risks: List[Any],
) -> List[str]:
    ranked = _sort_patterns([p for p in patterns])
    pattern_strings = prioritize_actions_from_patterns(ranked, patient_meta)
    synthetic: List[Any] = [
        {
            "domain": "Клинический приоритет",
            "what": txt,
            "why": "Связано с выявленным паттерном",
            "priority": "high",
        }
        for txt in pattern_strings
    ]
    merged_steps: List[Any] = list(synthetic)
    merged_steps.extend([s for s in steps if _step_visible(s)])
    age = _patient_age_int(patient_meta)
    risk_list = _risks_list_from_meta_and_explicit(patient_meta, risks)
    pa = prioritize_actions(
        patterns=list(patterns),
        next_steps=merged_steps,
        risks=risk_list,
        patient_age=age,
    )
    return prioritized_actions_to_strings(pa, limit=8)


def build_summary_output(data: SummaryBuildInput) -> SummaryBuildOutput:
    pm = dict(data.patient_meta or {})
    main, ui_headline = _build_main_conclusion_from_patterns(
        list(data.clinical_patterns),
        fallback_summary=data.fallback_summary,
        patient_meta=pm,
    )
    attention_items = _build_attention_items(list(data.clinical_patterns), list(data.findings))
    next_steps_items = _build_next_steps_combined(
        list(data.clinical_patterns),
        list(data.next_steps),
        pm,
        list(data.risks or []),
    )
    return SummaryBuildOutput(
        main_conclusion=main,
        ui_headline=ui_headline,
        attention_items=attention_items,
        next_steps_items=next_steps_items,
    )


def build_summary_dict(data: SummaryBuildInput) -> dict[str, Any]:
    out = build_summary_output(data)
    return {
        "main_conclusion": out.main_conclusion,
        "ui_headline": out.ui_headline,
        "attention_items": out.attention_items,
        "next_steps_items": out.next_steps_items,
    }


def _risks_from_core(core: ClinicalCoreResult) -> List[Any]:
    out: List[Any] = []
    r = getattr(core, "risk", None)
    if r is not None:
        dr = getattr(r, "domain_risks", None) or []
        out.extend(list(dr))
    rd = getattr(core, "risk_domains", None) or []
    out.extend(list(rd))
    return out


def build_summary_structured_from_core(
    core: ClinicalCoreResult,
    patterns: List[ClinicalPattern],
    patient_meta: Optional[dict[str, Any]] = None,
) -> SummaryBuildOutput:
    """Точка входа из integration: core + отранжированные паттерны."""
    meta = dict(patient_meta or {})
    age = meta.get("age_years")
    is_pediatric = False
    if age is not None:
        try:
            is_pediatric = float(age) < 18.0
        except (TypeError, ValueError):
            pass

    fb = (core.summary or "").strip()
    if _is_technical_text(fb):
        fb = ""

    inp = SummaryBuildInput(
        clinical_patterns=patterns,
        findings=list(core.final_findings or []),
        next_steps=list(core.next_steps or []),
        risks=_risks_from_core(core),
        fallback_summary=fb,
        is_pediatric=is_pediatric,
        patient_meta=meta,
    )
    return build_summary_output(inp)


# Совместимость со старым именем
def build_integrated_summary(ranked: List[ClinicalPattern], patient_meta: dict[str, Any]) -> str:
    """Только текст вывода (без блоков UI)."""
    meta = dict(patient_meta or {})
    try:
        is_ped = float(meta.get("age_years") or 99) < 18
    except (TypeError, ValueError):
        is_ped = False
    out = build_summary_output(
        SummaryBuildInput(
            clinical_patterns=ranked,
            findings=[],
            next_steps=[],
            risks=[],
            fallback_summary="",
            is_pediatric=is_ped,
            patient_meta=meta,
        )
    )
    return out.main_conclusion
