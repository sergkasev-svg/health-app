"""
P0 rules: Urinalysis / ОАМ.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.clinical_engine.p0_rules.contract import MarkerSnapshot, RuleResult
from app.services.clinical_engine.p0_rules.helpers import get_marker, has_finding, is_positive_qualitative, numeric_or_positive


def build_findings(values: Dict[str, MarkerSnapshot]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    uti = (
        is_positive_qualitative(values, "leukocytes")
        or is_positive_qualitative(values, "nitrites")
        or is_positive_qualitative(values, "bacteria")
    )
    if uti:
        findings.append(
            {
                "code": "uti_signal",
                "title": "Возможен воспалительный/инфекционный сигнал в мочевых путях",
                "group": "Мочевой осадок",
                "severity": "moderate",
                "primary_marker": "leukocytes",
                "supporting_markers": ["nitrites", "bacteria"],
                "comment": "Требует сопоставления с жалобами и клиникой.",
            }
        )
    if numeric_or_positive(values, "blood_reaction"):
        findings.append(
            {
                "code": "blood_reaction_positive",
                "title": "Положительная реакция на кровь",
                "group": "Кровь/эритроциты",
                "severity": "mild",
                "primary_marker": "blood_reaction",
                "supporting_markers": ["erythrocytes"],
                "comment": "Изолированный сигнал требует оценки в клиническом контексте.",
            }
        )
    if is_positive_qualitative(values, "erythrocytes"):
        findings.append(
            {
                "code": "hematuria_signal",
                "title": "Обнаружены эритроциты в моче",
                "group": "Кровь/эритроциты",
                "severity": "moderate",
                "primary_marker": "erythrocytes",
                "supporting_markers": ["blood_reaction"],
                "comment": "Требует клинической оценки.",
            }
        )
    if is_positive_qualitative(values, "protein"):
        findings.append(
            {
                "code": "proteinuria_signal",
                "title": "Обнаружен белок в моче",
                "group": "Белок",
                "severity": "moderate",
                "primary_marker": "protein",
                "supporting_markers": [],
                "comment": "Требует клинической оценки и при необходимости контроля.",
            }
        )
    if is_positive_qualitative(values, "glucose"):
        findings.append(
            {
                "code": "glycosuria_signal",
                "title": "Глюкоза в моче",
                "group": "Глюкоза/кетоны",
                "severity": "moderate",
                "primary_marker": "glucose",
                "supporting_markers": [],
                "comment": "Требует оценки углеводного обмена.",
            }
        )
    if is_positive_qualitative(values, "ketones"):
        findings.append(
            {
                "code": "ketonuria_signal",
                "title": "Кетоны в моче",
                "group": "Глюкоза/кетоны",
                "severity": "mild",
                "primary_marker": "ketones",
                "supporting_markers": [],
                "comment": "Оценка в клиническом контексте.",
            }
        )
    sg = get_marker(values, "specific_gravity")
    if sg and sg.ref_low is not None and sg.value is not None and sg.value < sg.ref_low:
        margin = sg.ref_low - 5
        sev = "borderline" if sg.value >= margin else "mild"
        findings.append(
            {
                "code": "low_specific_gravity",
                "title": "Снижена относительная плотность мочи",
                "group": "Концентрационная функция",
                "severity": sev,
                "primary_marker": "specific_gravity",
                "supporting_markers": [],
                "comment": "Возможна относительно разбавленная моча; без контекста самостоятельной диагностической ценности не имеет.",
            }
        )
    if sg and sg.ref_high is not None and sg.value is not None and sg.value > sg.ref_high:
        findings.append(
            {
                "code": "high_specific_gravity",
                "title": "Повышена относительная плотность мочи",
                "group": "Концентрационная функция",
                "severity": "mild",
                "primary_marker": "specific_gravity",
                "supporting_markers": [],
                "comment": "Возможна концентрированная моча; оценка с клиникой.",
            }
        )
    return findings


def build_hypotheses(values: Dict[str, MarkerSnapshot], findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    hy: List[Dict[str, Any]] = []
    if has_finding(findings, "uti_signal"):
        hy.append(
            {
                "code": "possible_uti_pattern",
                "label": "Возможен паттерн воспаления мочевых путей",
                "confidence": 0.8,
                "patient_visible": False,
            }
        )
    if has_finding(findings, "blood_reaction_positive") and not has_finding(findings, "hematuria_signal"):
        hy.append(
            {
                "code": "isolated_blood_reaction",
                "label": "Изолированная положительная реакция на кровь без явной гематурии",
                "confidence": 0.7,
                "patient_visible": False,
            }
        )
    if has_finding(findings, "proteinuria_signal"):
        hy.append(
            {
                "code": "proteinuria_pattern",
                "label": "Требует оценки паттерн протеинурии",
                "confidence": 0.75,
                "patient_visible": False,
            }
        )
    return hy


def build_next_steps(findings: List[Dict[str, Any]], hypotheses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    if has_finding(findings, "uti_signal"):
        steps.append(
            {
                "domain": "Мочевые пути",
                "what": "Очная оценка врача при наличии симптомов",
                "why": "Уточнение возможного воспалительного процесса",
                "priority": "high",
            }
        )
    if has_finding(findings, "blood_reaction_positive"):
        steps.append(
            {
                "domain": "Мочевые пути",
                "what": "Контрольный ОАМ при стойком сигнале или жалобах",
                "why": "Оценка стойкости сигнала",
                "priority": "medium",
            }
        )
    if has_finding(findings, "proteinuria_signal"):
        steps.append(
            {
                "domain": "Почки",
                "what": "Повтор ОАМ / альбумин-креатинин мочи по показаниям",
                "why": "Уточнение протеинурии",
                "priority": "medium",
            }
        )
    return steps


def build_risk(findings: List[Dict[str, Any]], hypotheses: List[Dict[str, Any]]) -> Dict[str, Any]:
    score = 0
    if has_finding(findings, "uti_signal"):
        score += 3
    if has_finding(findings, "hematuria_signal"):
        score += 3
    if has_finding(findings, "proteinuria_signal"):
        score += 3
    if has_finding(findings, "blood_reaction_positive"):
        score += 1
    level = "low"
    if score >= 6:
        level = "high"
    elif score >= 3:
        level = "moderate"
    return {
        "domain": "urinary",
        "level": level,
        "score": score,
        "drivers": [f.get("code") for f in findings if f.get("code")],
        "summary": "Риск по ОАМ: низкий/умеренный/высокий — ориентир для врача, не диагноз.",
    }


def build_rule_result(values: Dict[str, MarkerSnapshot]) -> RuleResult:
    findings = build_findings(values)
    hypotheses = build_hypotheses(values, findings)
    next_steps = build_next_steps(findings, hypotheses)
    risk = build_risk(findings, hypotheses)
    return RuleResult(findings=findings, hypotheses=hypotheses, next_steps=next_steps, risk=risk)
