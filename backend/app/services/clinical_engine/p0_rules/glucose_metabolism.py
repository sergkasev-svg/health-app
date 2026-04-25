"""
P0 rules: углеводный обмен (глюкоза, HbA1c, фруктозамин, HOMA-IR).
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.clinical_engine.p0_rules.contract import MarkerSnapshot, RuleResult
from app.services.clinical_engine.p0_rules.helpers import get_marker, has_finding


def build_findings(values: Dict[str, MarkerSnapshot]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    hba1c = get_marker(values, "hba1c")
    if hba1c and hba1c.value is not None:
        if hba1c.value >= 6.5:
            findings.append(
                {
                    "code": "diabetic_hba1c_range",
                    "title": "HbA1c в диабетическом диапазоне",
                    "group": "Углеводный обмен",
                    "severity": "high",
                    "primary_marker": "hba1c",
                    "supporting_markers": ["fasting_glucose", "glucose"],
                    "comment": "Требует клинического подтверждения и оценки врачом.",
                }
            )
        elif 5.7 <= hba1c.value < 6.5:
            findings.append(
                {
                    "code": "prediabetic_hba1c_range",
                    "title": "HbA1c выше оптимального диапазона",
                    "group": "Углеводный обмен",
                    "severity": "moderate",
                    "primary_marker": "hba1c",
                    "supporting_markers": ["fasting_glucose", "glucose"],
                    "comment": "Требует уточнения углеводного обмена.",
                }
            )
    fg = get_marker(values, "fasting_glucose")
    if fg is None:
        fg = get_marker(values, "glucose")
    if fg and fg.ref_high is not None and fg.value is not None and fg.value > fg.ref_high:
        primary = "fasting_glucose" if get_marker(values, "fasting_glucose") is fg else "glucose"
        findings.append(
            {
                "code": "fasting_glucose_elevated",
                "title": "Повышена глюкоза",
                "group": "Углеводный обмен",
                "severity": "moderate",
                "primary_marker": primary,
                "supporting_markers": ["hba1c"],
                "comment": "Оценка натощак / контекст обязательны.",
            }
        )
    fr = get_marker(values, "fructosamine")
    if fr and fr.ref_high is not None and fr.value is not None and fr.value > fr.ref_high:
        findings.append(
            {
                "code": "fructosamine_elevated",
                "title": "Повышен фруктозамин",
                "group": "Углеводный обмен",
                "severity": "mild",
                "primary_marker": "fructosamine",
                "supporting_markers": ["hba1c"],
                "comment": "Требует сопоставления с глюкозой и HbA1c.",
            }
        )
    homa = get_marker(values, "homa_ir")
    ins = get_marker(values, "insulin")
    if homa and homa.ref_high is not None and homa.value is not None and homa.value > homa.ref_high:
        findings.append(
            {
                "code": "insulin_resistance_signal",
                "title": "Сигнал инсулинорезистентности",
                "group": "Углеводный обмен",
                "severity": "moderate",
                "primary_marker": "homa_ir",
                "supporting_markers": ["insulin", "fasting_glucose", "glucose"],
                "comment": "Требует клинической оценки.",
            }
        )
    return findings


def build_hypotheses(values: Dict[str, MarkerSnapshot], findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    hy: List[Dict[str, Any]] = []
    if has_finding(findings, "diabetic_hba1c_range") or has_finding(findings, "fasting_glucose_elevated"):
        hy.append(
            {
                "code": "glucose_metabolism_disorder",
                "label": "Возможен клинически значимый паттерн нарушения углеводного обмена",
                "confidence": 0.85,
                "patient_visible": False,
            }
        )
    if has_finding(findings, "fructosamine_elevated") and not has_finding(findings, "diabetic_hba1c_range"):
        hy.append(
            {
                "code": "short_term_glycemia_discrepancy",
                "label": "Возможны ранние или нестойкие нарушения углеводного обмена",
                "confidence": 0.7,
                "patient_visible": False,
            }
        )
    if has_finding(findings, "insulin_resistance_signal"):
        hy.append(
            {
                "code": "insulin_resistance_pattern",
                "label": "Возможен паттерн инсулинорезистентности",
                "confidence": 0.8,
                "patient_visible": False,
            }
        )
    return hy


def build_next_steps(findings: List[Dict[str, Any]], hypotheses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    if has_finding(findings, "prediabetic_hba1c_range") or has_finding(findings, "fasting_glucose_elevated") or has_finding(findings, "fructosamine_elevated"):
        steps.append(
            {
                "domain": "Углеводный обмен",
                "what": "Повторная глюкоза натощак",
                "why": "Подтверждение отклонения",
                "priority": "high",
            }
        )
    if has_finding(findings, "fructosamine_elevated"):
        steps.append(
            {
                "domain": "Углеводный обмен",
                "what": "Сопоставление с HbA1c и клиническим контекстом",
                "why": "Уточнение расхождения маркеров",
                "priority": "medium",
            }
        )
    if has_finding(findings, "insulin_resistance_signal"):
        steps.append(
            {
                "domain": "Углеводный обмен",
                "what": "Инсулин / HOMA-IR в динамике по показаниям",
                "why": "Оценка инсулинорезистентности",
                "priority": "medium",
            }
        )
    return steps


def build_risk(findings: List[Dict[str, Any]], hypotheses: List[Dict[str, Any]]) -> Dict[str, Any]:
    score = 0
    if has_finding(findings, "diabetic_hba1c_range"):
        score += 4
    if has_finding(findings, "fasting_glucose_elevated"):
        score += 3
    if has_finding(findings, "prediabetic_hba1c_range"):
        score += 2
    if has_finding(findings, "fructosamine_elevated"):
        score += 1
    if has_finding(findings, "insulin_resistance_signal"):
        score += 2
    level = "low"
    if score >= 6:
        level = "high"
    elif score >= 3:
        level = "moderate"
    return {
        "domain": "glucose_metabolism",
        "level": level,
        "score": score,
        "drivers": [f.get("code") for f in findings if f.get("code")],
        "summary": "Риск по углеводному обмену — ориентир; диагноз только врачом.",
    }


def build_rule_result(values: Dict[str, MarkerSnapshot]) -> RuleResult:
    findings = build_findings(values)
    hypotheses = build_hypotheses(values, findings)
    next_steps = build_next_steps(findings, hypotheses)
    risk = build_risk(findings, hypotheses)
    return RuleResult(findings=findings, hypotheses=hypotheses, next_steps=next_steps, risk=risk)
