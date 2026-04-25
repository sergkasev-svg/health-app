"""
P0 rules: CBC + ретикулоциты. Расширяет cbc.py дополнительными маркерами эритропоэза.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.clinical_engine.p0_rules import cbc
from app.services.clinical_engine.p0_rules.contract import MarkerSnapshot, RuleResult
from app.services.clinical_engine.p0_rules.helpers import get_marker, has_finding


def build_findings(values: Dict[str, MarkerSnapshot]) -> List[Dict[str, Any]]:
    findings = cbc.build_findings(values)
    codes = {f["code"] for f in findings}
    ret_abs = get_marker(values, "reticulocytes_abs")
    if ret_abs and ret_abs.ref_low is not None and ret_abs.value is not None and ret_abs.value < ret_abs.ref_low:
        if "low_reticulocytes" not in codes:
            findings.append(
                {
                    "code": "low_reticulocytes",
                    "title": "Снижены ретикулоциты",
                    "group": "Эритропоэз",
                    "severity": "mild",
                    "primary_marker": "reticulocytes_abs",
                    "supporting_markers": ["hb"],
                    "comment": "Снижение регенераторной активности эритропоэза.",
                }
            )
    if ret_abs and ret_abs.ref_high is not None and ret_abs.value is not None and ret_abs.value > ret_abs.ref_high:
        if "high_reticulocytes" not in codes:
            findings.append(
                {
                    "code": "high_reticulocytes",
                    "title": "Повышены ретикулоциты",
                    "group": "Эритропоэз",
                    "severity": "mild",
                    "primary_marker": "reticulocytes_abs",
                    "supporting_markers": ["hb"],
                    "comment": "Повышенная регенераторная активность эритропоэза.",
                }
            )
    return findings


def build_hypotheses(values: Dict[str, MarkerSnapshot], findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    hy = cbc.build_hypotheses(values, findings)
    hy_codes = {h["code"] for h in hy}
    if has_finding(findings, "anemia_signal") and has_finding(findings, "low_reticulocytes"):
        if "hypoproliferative_erythropoiesis" not in hy_codes:
            hy.append(
                {
                    "code": "hypoproliferative_erythropoiesis",
                    "label": "Возможен гипопролиферативный эритропоэз",
                    "confidence": 0.8,
                    "patient_visible": False,
                }
            )
    if has_finding(findings, "anemia_signal") and has_finding(findings, "high_reticulocytes"):
        if "regenerative_response" not in hy_codes:
            hy.append(
                {
                    "code": "regenerative_response",
                    "label": "Возможен регенераторный ответ костного мозга",
                    "confidence": 0.75,
                    "patient_visible": False,
                }
            )
    return hy


def build_next_steps(findings: List[Dict[str, Any]], hypotheses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    steps = cbc.build_next_steps(findings, hypotheses)
    if has_finding(findings, "low_reticulocytes"):
        steps.append(
            {
                "domain": "Эритропоэз",
                "what": "Ферритин / B12 / фолат",
                "why": "Уточнение причин снижения эритропоэза",
                "priority": "high",
            }
        )
    return steps


def build_risk(findings: List[Dict[str, Any]], hypotheses: List[Dict[str, Any]]) -> Dict[str, Any]:
    base = cbc.build_risk(findings, hypotheses)
    # лёгкое усиление при выраженной регенераторной дисфункции
    if has_finding(findings, "low_reticulocytes") and base.get("level") == "low":
        base = {**base, "score": base.get("score", 0) + 1, "summary": base.get("summary", "") + " Учтён сигнал по ретикулоцитам."}
    return base


def build_rule_result(values: Dict[str, MarkerSnapshot]) -> RuleResult:
    findings = build_findings(values)
    hypotheses = build_hypotheses(values, findings)
    next_steps = build_next_steps(findings, hypotheses)
    risk = build_risk(findings, hypotheses)
    return RuleResult(findings=findings, hypotheses=hypotheses, next_steps=next_steps, risk=risk)
