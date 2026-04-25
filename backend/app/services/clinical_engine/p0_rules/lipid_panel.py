"""
P0 rules: липидный профиль.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.clinical_engine.p0_rules.contract import MarkerSnapshot, RuleResult
from app.services.clinical_engine.p0_rules.helpers import get_marker, has_finding


def build_findings(values: Dict[str, MarkerSnapshot]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    tc = get_marker(values, "total_cholesterol")
    if tc and tc.value is not None and tc.value > 7.0:
        findings.append(
            {
                "code": "severe_hypercholesterolemia",
                "title": "Выраженная гиперхолестеринемия",
                "group": "Липидный обмен",
                "severity": "high",
                "primary_marker": "total_cholesterol",
                "supporting_markers": ["ldl_cholesterol"],
                "comment": "Клинически значимая дислипидемия.",
            }
        )
    ldl = get_marker(values, "ldl_cholesterol")
    if ldl and ldl.value is not None and ldl.value > 5.0:
        findings.append(
            {
                "code": "marked_ldl_elevation",
                "title": "Значимое повышение ЛПНП",
                "group": "Липидный обмен",
                "severity": "high",
                "primary_marker": "ldl_cholesterol",
                "supporting_markers": ["total_cholesterol"],
                "comment": "Повышенный атерогенный риск.",
            }
        )
    tg = get_marker(values, "triglycerides")
    if tg and tg.ref_high is not None and tg.value is not None and tg.value > tg.ref_high:
        findings.append(
            {
                "code": "hypertriglyceridemia",
                "title": "Повышены триглицериды",
                "group": "Липидный обмен",
                "severity": "moderate",
                "primary_marker": "triglycerides",
                "supporting_markers": [],
                "comment": "Требует оценки метаболического контекста.",
            }
        )
    hdl = get_marker(values, "hdl_cholesterol")
    if hdl and hdl.ref_low is not None and hdl.value is not None and hdl.value < hdl.ref_low:
        findings.append(
            {
                "code": "low_hdl",
                "title": "Снижен ЛПВП",
                "group": "Липидный обмен",
                "severity": "mild",
                "primary_marker": "hdl_cholesterol",
                "supporting_markers": [],
                "comment": "Неблагоприятный липидный профиль.",
            }
        )
    lpa = get_marker(values, "lp_a")
    if lpa and lpa.ref_high is not None and lpa.value is not None and lpa.value > lpa.ref_high:
        findings.append(
            {
                "code": "lp_a_elevated",
                "title": "Повышен липопротеин (а)",
                "group": "Липидный обмен",
                "severity": "moderate",
                "primary_marker": "lp_a",
                "supporting_markers": [],
                "comment": "Дополнительный атерогенный фактор; интерпретация врачом.",
            }
        )
    return findings


def build_hypotheses(values: Dict[str, MarkerSnapshot], findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    hy: List[Dict[str, Any]] = []
    if has_finding(findings, "marked_ldl_elevation") or has_finding(findings, "severe_hypercholesterolemia"):
        hy.extend(
            [
                {
                    "code": "atherogenic_dyslipidemia",
                    "label": "Атерогенная дислипидемия",
                    "confidence": 0.95,
                    "patient_visible": False,
                },
                {
                    "code": "possible_familial_hypercholesterolemia",
                    "label": "Возможна первичная/семейная гиперхолестеринемия",
                    "confidence": 0.7,
                    "patient_visible": False,
                },
            ]
        )
    return hy


def build_next_steps(findings: List[Dict[str, Any]], hypotheses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    if has_finding(findings, "marked_ldl_elevation") or has_finding(findings, "severe_hypercholesterolemia"):
        steps.extend(
            [
                {
                    "domain": "Липидный обмен",
                    "what": "Повторная липидограмма натощак",
                    "why": "Подтверждение стойкости отклонений",
                    "priority": "high",
                },
                {
                    "domain": "Липидный обмен",
                    "what": "ApoB / non-HDL-C",
                    "why": "Уточнение атерогенной нагрузки",
                    "priority": "medium",
                },
                {
                    "domain": "Эндокринология",
                    "what": "ТТГ",
                    "why": "Исключение вторичных причин дислипидемии",
                    "priority": "medium",
                },
            ]
        )
    return steps


def build_risk(findings: List[Dict[str, Any]], hypotheses: List[Dict[str, Any]]) -> Dict[str, Any]:
    score = 0
    if has_finding(findings, "marked_ldl_elevation"):
        score += 4
    if has_finding(findings, "severe_hypercholesterolemia"):
        score += 3
    if has_finding(findings, "hypertriglyceridemia"):
        score += 2
    if has_finding(findings, "low_hdl"):
        score += 1
    level = "low"
    if score >= 6:
        level = "high"
    elif score >= 3:
        level = "moderate"
    return {
        "domain": "cardiometabolic",
        "level": level,
        "score": score,
        "drivers": [f.get("code") for f in findings if f.get("code")],
        "summary": "Кардиометаболический риск по липидам — ориентир для врача.",
    }


def build_rule_result(values: Dict[str, MarkerSnapshot]) -> RuleResult:
    findings = build_findings(values)
    hypotheses = build_hypotheses(values, findings)
    next_steps = build_next_steps(findings, hypotheses)
    risk = build_risk(findings, hypotheses)
    return RuleResult(findings=findings, hypotheses=hypotheses, next_steps=next_steps, risk=risk)
