"""
P0 rules: CBC / ОАК. Вход: Dict[str, MarkerSnapshot] (см. adapters.labvalues_to_cbc_map).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.clinical_engine.p0_rules.contract import MarkerSnapshot, RuleResult
from app.services.clinical_engine.p0_rules.helpers import get_marker, has_finding


def _m(values: Dict[str, MarkerSnapshot], code: str) -> Optional[MarkerSnapshot]:
    return get_marker(values, code)


def build_findings(values: Dict[str, MarkerSnapshot]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    hb = _m(values, "hb")
    if hb and hb.ref_low is not None and hb.value is not None and hb.value < hb.ref_low:
        findings.append(
            {
                "code": "anemia_signal",
                "title": "Снижен гемоглобин",
                "group": "Эритроциты, гемоглобин",
                "severity": "moderate",
                "primary_marker": "hb",
                "supporting_markers": ["rbc", "hct"],
                "comment": "Требует оценки анемического паттерна.",
            }
        )
    mcv = _m(values, "mcv")
    if mcv and mcv.ref_low is not None and mcv.value is not None and mcv.value < mcv.ref_low:
        findings.append(
            {
                "code": "microcytosis",
                "title": "Снижен MCV",
                "group": "Эритроциты, гемоглобин",
                "severity": "mild",
                "primary_marker": "mcv",
                "supporting_markers": ["mch", "rdw"],
                "comment": "Микроцитарный паттерн; возможен дефицит железа.",
            }
        )
    mch = _m(values, "mch")
    if mch and mch.ref_low is not None and mch.value is not None and mch.value < mch.ref_low:
        findings.append(
            {
                "code": "low_mch",
                "title": "Снижено содержание гемоглобина в эритроците",
                "group": "Эритроциты, гемоглобин",
                "severity": "mild",
                "primary_marker": "mch",
                "supporting_markers": ["hb", "mcv"],
                "comment": "Может соответствовать раннему железодефицитному паттерну.",
            }
        )
    if mcv and mcv.ref_high is not None and mcv.value is not None and mcv.value > mcv.ref_high:
        findings.append(
            {
                "code": "macrocytosis",
                "title": "Повышен MCV",
                "group": "Эритроциты, гемоглобин",
                "severity": "mild",
                "primary_marker": "mcv",
                "supporting_markers": ["hb"],
                "comment": "Макроцитарный паттерн требует оценки B12/фолата и других причин.",
            }
        )
    wbc = _m(values, "wbc")
    if wbc and wbc.ref_high is not None and wbc.value is not None and wbc.value > wbc.ref_high:
        findings.append(
            {
                "code": "leukocytosis",
                "title": "Повышены лейкоциты",
                "group": "Лейкоциты, формула",
                "severity": "moderate",
                "primary_marker": "wbc",
                "supporting_markers": [],
                "comment": "Требует оценки в клиническом контексте.",
            }
        )
    if wbc and wbc.ref_low is not None and wbc.value is not None and wbc.value < wbc.ref_low:
        findings.append(
            {
                "code": "leukopenia",
                "title": "Снижены лейкоциты",
                "group": "Лейкоциты, формула",
                "severity": "moderate",
                "primary_marker": "wbc",
                "supporting_markers": [],
                "comment": "Требует оценки в клиническом контексте.",
            }
        )
    neu_abs = _m(values, "neutrophils_abs")
    neu_pct = _m(values, "neutrophils_pct")
    if (neu_abs and neu_abs.ref_high is not None and neu_abs.value is not None and neu_abs.value > neu_abs.ref_high) or (
        neu_pct and neu_pct.ref_high is not None and neu_pct.value is not None and neu_pct.value > neu_pct.ref_high
    ):
        findings.append(
            {
                "code": "neutrophilic_shift",
                "title": "Нейтрофильный сдвиг",
                "group": "Лейкоциты, формула",
                "severity": "moderate",
                "primary_marker": "neutrophils_abs",
                "supporting_markers": ["wbc", "esr"],
                "comment": "Может соответствовать бактериальному воспалительному сигналу.",
            }
        )
    lym_abs = _m(values, "lymphocytes_abs")
    lym_pct = _m(values, "lymphocytes_pct")
    if (lym_abs and lym_abs.ref_high is not None and lym_abs.value is not None and lym_abs.value > lym_abs.ref_high) or (
        lym_pct and lym_pct.ref_high is not None and lym_pct.value is not None and lym_pct.value > lym_pct.ref_high
    ):
        findings.append(
            {
                "code": "lymphocytic_shift",
                "title": "Лимфоцитарный сдвиг",
                "group": "Лейкоциты, формула",
                "severity": "mild",
                "primary_marker": "lymphocytes_abs",
                "supporting_markers": ["wbc"],
                "comment": "Требует оценки в клиническом контексте.",
            }
        )
    eos_pct = _m(values, "eosinophils_pct")
    eos_abs = _m(values, "eosinophils_abs")
    if (eos_pct and eos_pct.ref_high is not None and eos_pct.value is not None and eos_pct.value > eos_pct.ref_high) or (
        eos_abs and eos_abs.ref_high is not None and eos_abs.value is not None and eos_abs.value > eos_abs.ref_high
    ):
        findings.append(
            {
                "code": "eosinophilic_signal",
                "title": "Повышены эозинофилы",
                "group": "Лейкоциты, формула",
                "severity": "mild",
                "primary_marker": "eosinophils_pct",
                "supporting_markers": ["eosinophils_abs"],
                "comment": "Возможен аллергический, паразитарный или лекарственный контекст.",
            }
        )
    plt = _m(values, "plt")
    if plt and plt.ref_low is not None and plt.value is not None and plt.value < plt.ref_low:
        findings.append(
            {
                "code": "thrombocytopenia",
                "title": "Снижены тромбоциты",
                "group": "Тромбоциты",
                "severity": "high",
                "primary_marker": "plt",
                "supporting_markers": [],
                "comment": "Требует клинической оценки.",
            }
        )
    if plt and plt.ref_high is not None and plt.value is not None and plt.value > plt.ref_high:
        findings.append(
            {
                "code": "thrombocytosis",
                "title": "Повышены тромбоциты",
                "group": "Тромбоциты",
                "severity": "moderate",
                "primary_marker": "plt",
                "supporting_markers": [],
                "comment": "Требует оценки в клиническом контексте.",
            }
        )
    esr = _m(values, "esr")
    if esr and esr.ref_high is not None and esr.value is not None and esr.value > esr.ref_high:
        sev = "borderline" if esr.value <= esr.ref_high * 1.2 else "mild"
        findings.append(
            {
                "code": "esr_elevation",
                "title": "Ускорена СОЭ",
                "group": "Воспалительные маркеры",
                "severity": sev,
                "primary_marker": "esr",
                "supporting_markers": ["wbc"],
                "comment": "Неспецифический сигнал, оценивается только в клиническом контексте.",
            }
        )
    return findings


def build_hypotheses(values: Dict[str, MarkerSnapshot], findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    hy: List[Dict[str, Any]] = []
    if has_finding(findings, "anemia_signal") and (has_finding(findings, "microcytosis") or has_finding(findings, "low_mch")):
        hy.append(
            {
                "code": "iron_deficiency_pattern",
                "label": "Возможен железодефицитный паттерн",
                "confidence": 0.8,
                "patient_visible": False,
            }
        )
    if has_finding(findings, "neutrophilic_shift") and has_finding(findings, "esr_elevation"):
        hy.append(
            {
                "code": "inflammatory_pattern",
                "label": "Возможен воспалительный паттерн",
                "confidence": 0.75,
                "patient_visible": False,
            }
        )
    if has_finding(findings, "eosinophilic_signal"):
        hy.append(
            {
                "code": "allergic_or_parasitic_context",
                "label": "Возможен аллергический/паразитарный контекст",
                "confidence": 0.65,
                "patient_visible": False,
            }
        )
    return hy


def build_next_steps(findings: List[Dict[str, Any]], hypotheses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    if has_finding(findings, "anemia_signal") or has_finding(findings, "microcytosis") or has_finding(findings, "low_mch"):
        steps.extend(
            [
                {
                    "domain": "Железный обмен",
                    "what": "Ферритин",
                    "why": "Уточнение железодефицитного паттерна",
                    "priority": "high",
                },
                {
                    "domain": "Железный обмен",
                    "what": "Сывороточное железо / трансферрин / ОЖСС",
                    "why": "Уточнение обмена железа",
                    "priority": "medium",
                },
            ]
        )
    if has_finding(findings, "neutrophilic_shift") or has_finding(findings, "esr_elevation"):
        steps.append(
            {
                "domain": "Воспаление",
                "what": "CRP",
                "why": "Уточнение воспалительного сигнала",
                "priority": "medium",
            }
        )
    if has_finding(findings, "eosinophilic_signal"):
        steps.append(
            {
                "domain": "Аллергия/паразиты",
                "what": "IgE / паразитологическое обследование по показаниям",
                "why": "Уточнение причины эозинофилии",
                "priority": "medium",
            }
        )
    return steps


def build_risk(findings: List[Dict[str, Any]], hypotheses: List[Dict[str, Any]]) -> Dict[str, Any]:
    score = 0
    if has_finding(findings, "thrombocytopenia"):
        score += 4
    if has_finding(findings, "anemia_signal"):
        score += 3
    if has_finding(findings, "neutrophilic_shift"):
        score += 2
    if has_finding(findings, "esr_elevation"):
        score += 1
    level = "low"
    if score >= 6:
        level = "high"
    elif score >= 3:
        level = "moderate"
    drivers = [f["code"] for f in findings if f.get("code")]
    return {
        "domain": "hematology",
        "level": level,
        "score": score,
        "drivers": drivers[:12],
        "summary": _risk_summary_cbc(level, score),
    }


def _risk_summary_cbc(level: str, score: int) -> str:
    if level == "high":
        return "Повышенный риск значимых гематологических отклонений по данному анализу."
    if level == "moderate":
        return "Умеренный риск; рекомендуется уточнение и динамика."
    return "Низкий риск по автоматической оценке; интерпретация врачом обязательна."


def build_rule_result(values: Dict[str, MarkerSnapshot]) -> RuleResult:
    findings = build_findings(values)
    hypotheses = build_hypotheses(values, findings)
    next_steps = build_next_steps(findings, hypotheses)
    risk = build_risk(findings, hypotheses)
    return RuleResult(findings=findings, hypotheses=hypotheses, next_steps=next_steps, risk=risk)
