"""
P0 rules: базовая биохимия крови.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.clinical_engine.p0_rules.contract import MarkerSnapshot, RuleResult
from app.services.clinical_engine.p0_rules.helpers import get_marker, has_finding


def build_findings(values: Dict[str, MarkerSnapshot]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    alt = get_marker(values, "alt")
    if alt and alt.ref_high is not None and alt.value is not None and alt.value > alt.ref_high:
        sev = "high" if alt.value >= alt.ref_high * 3 else "mild"
        findings.append(
            {
                "code": "alt_elevation",
                "title": "Повышен АЛТ",
                "group": "Печень",
                "severity": sev,
                "primary_marker": "alt",
                "supporting_markers": ["ast", "bilirubin_total"],
                "comment": "Требует оценки печёночного профиля.",
            }
        )
    ast = get_marker(values, "ast")
    if ast and ast.ref_high is not None and ast.value is not None and ast.value > ast.ref_high:
        sev = "high" if ast.value >= ast.ref_high * 3 else "mild"
        findings.append(
            {
                "code": "ast_elevation",
                "title": "Повышен АСТ",
                "group": "Печень",
                "severity": sev,
                "primary_marker": "ast",
                "supporting_markers": ["alt", "bilirubin_total"],
                "comment": "Требует оценки печёночного профиля.",
            }
        )
    bili = get_marker(values, "bilirubin_total")
    if bili and bili.ref_high is not None and bili.value is not None and bili.value > bili.ref_high:
        findings.append(
            {
                "code": "bilirubin_elevation",
                "title": "Повышен билирубин",
                "group": "Печень/желчевыводящие пути",
                "severity": "moderate",
                "primary_marker": "bilirubin_total",
                "supporting_markers": ["bilirubin_direct", "alt", "ast"],
                "comment": "Требует оценки печёночного или холестатического контекста.",
            }
        )
    cr = get_marker(values, "creatinine")
    if cr and cr.ref_high is not None and cr.value is not None and cr.value > cr.ref_high:
        findings.append(
            {
                "code": "creatinine_elevation",
                "title": "Повышен креатинин",
                "group": "Почки",
                "severity": "moderate",
                "primary_marker": "creatinine",
                "supporting_markers": ["urea"],
                "comment": "Требует оценки функции почек.",
            }
        )
    alb = get_marker(values, "albumin")
    if alb and alb.ref_low is not None and alb.value is not None and alb.value < alb.ref_low:
        findings.append(
            {
                "code": "low_albumin",
                "title": "Снижен альбумин",
                "group": "Белковый обмен",
                "severity": "moderate",
                "primary_marker": "albumin",
                "supporting_markers": ["total_protein"],
                "comment": "Требует клинической оценки.",
            }
        )
    tp = get_marker(values, "total_protein")
    if tp and tp.ref_low is not None and tp.value is not None and tp.value < tp.ref_low:
        findings.append(
            {
                "code": "low_total_protein",
                "title": "Снижен общий белок",
                "group": "Белковый обмен",
                "severity": "mild",
                "primary_marker": "total_protein",
                "supporting_markers": ["albumin"],
                "comment": "Требует оценки в контексте.",
            }
        )
    na = get_marker(values, "sodium")
    if na and na.ref_low is not None and na.value is not None and na.value < na.ref_low:
        findings.append(
            {
                "code": "hyponatremia_signal",
                "title": "Снижен натрий",
                "group": "Электролиты",
                "severity": "moderate",
                "primary_marker": "sodium",
                "supporting_markers": [],
                "comment": "Клиническая оценка обязательна.",
            }
        )
    k = get_marker(values, "potassium")
    if k and k.ref_high is not None and k.value is not None and k.value > k.ref_high:
        findings.append(
            {
                "code": "hyperkalemia_signal",
                "title": "Повышен калий",
                "group": "Электролиты",
                "severity": "high",
                "primary_marker": "potassium",
                "supporting_markers": [],
                "comment": "Требует срочной клинической оценки при выраженном отклонении.",
            }
        )
    return findings


def build_hypotheses(values: Dict[str, MarkerSnapshot], findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    hy: List[Dict[str, Any]] = []
    if has_finding(findings, "alt_elevation") or has_finding(findings, "ast_elevation") or has_finding(findings, "bilirubin_elevation"):
        hy.append(
            {
                "code": "liver_pattern",
                "label": "Возможен печёночный паттерн",
                "confidence": 0.75,
                "patient_visible": False,
            }
        )
    if has_finding(findings, "creatinine_elevation"):
        hy.append(
            {
                "code": "renal_function_signal",
                "label": "Возможен сигнал снижения функции почек",
                "confidence": 0.8,
                "patient_visible": False,
            }
        )
    return hy


def build_next_steps(findings: List[Dict[str, Any]], hypotheses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    if has_finding(findings, "alt_elevation") or has_finding(findings, "ast_elevation") or has_finding(findings, "bilirubin_elevation"):
        steps.append(
            {
                "domain": "Печень",
                "what": "Расширенный печёночный профиль (ГГТ, ЩФ, фракции билирубина)",
                "why": "Уточнение характера отклонений",
                "priority": "medium",
            }
        )
    if has_finding(findings, "creatinine_elevation"):
        steps.append(
            {
                "domain": "Почки",
                "what": "eGFR / контроль креатинина",
                "why": "Уточнение функции почек",
                "priority": "high",
            }
        )
    return steps


def build_risk(findings: List[Dict[str, Any]], hypotheses: List[Dict[str, Any]]) -> Dict[str, Any]:
    score = 0
    if has_finding(findings, "hyperkalemia_signal"):
        score += 4
    if has_finding(findings, "creatinine_elevation"):
        score += 3
    if has_finding(findings, "alt_elevation"):
        score += 2
    if has_finding(findings, "bilirubin_elevation"):
        score += 2
    level = "low"
    if score >= 6:
        level = "high"
    elif score >= 3:
        level = "moderate"
    return {
        "domain": "metabolic_renal_hepatic",
        "level": level,
        "score": score,
        "drivers": [f.get("code") for f in findings if f.get("code")],
        "summary": "Сводный риск по базовой биохимии; не заменяет врача.",
    }


def build_rule_result(values: Dict[str, MarkerSnapshot]) -> RuleResult:
    findings = build_findings(values)
    hypotheses = build_hypotheses(values, findings)
    next_steps = build_next_steps(findings, hypotheses)
    risk = build_risk(findings, hypotheses)
    return RuleResult(findings=findings, hypotheses=hypotheses, next_steps=next_steps, risk=risk)
