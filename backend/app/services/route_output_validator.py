"""
Валидация согласованности вывода с маршрутом.
"""
from __future__ import annotations

import re
from typing import Any

from app.services.clinical_routing_models import ClinicalRouteDecision

_UTI = re.compile(r"цистит|пиелонефрит|инфекц\w*\s+мочевыводящих|нижних\s+мочевых", re.I)
_HIST = re.compile(r"гистамин|histamine|food\s+allergy", re.I)
_FOOD_Q = re.compile(r"вино|шоколад|фасол|цитрус|сыр", re.I)


def validate_no_blocked_hypotheses(
    user_hypotheses: list[str],
    route_decision: ClinicalRouteDecision,
) -> list[str]:
    errors: list[str] = []
    if route_decision.primary_route != "organic_acids_route":
        return errors
    for h in user_hypotheses or []:
        s = str(h or "")
        if _UTI.search(s):
            errors.append("blocked_hypothesis_leak:uti_in_organic_acids")
        if _HIST.search(s):
            errors.append("blocked_hypothesis_leak:histamine_in_organic_acids")
    return errors


def validate_no_blocked_questions(
    questions: list[str],
    route_decision: ClinicalRouteDecision,
) -> list[str]:
    errors: list[str] = []
    if route_decision.primary_route != "organic_acids_route":
        return errors
    for q in questions or []:
        if _FOOD_Q.search(str(q or "")):
            errors.append("blocked_question_leak:food_trigger_in_organic_acids")
    return errors


def validate_route_consistency(
    route_decision: ClinicalRouteDecision,
    user_hypotheses: list[str],
    questions: list[str],
) -> dict[str, Any]:
    h_err = validate_no_blocked_hypotheses(user_hypotheses, route_decision)
    q_err = validate_no_blocked_questions(questions, route_decision)
    all_e = h_err + q_err
    tags: list[str] = []
    if not all_e:
        tags.append("route_clean_case")
    if h_err:
        tags.append("blocked_hypothesis_leak")
    if q_err:
        tags.append("blocked_question_leak")
    return {
        "ok": len(all_e) == 0,
        "errors": all_e,
        "quality_tags": tags,
    }


def validate_physician_report_consistency(
    report_text: str,
    route_decision: ClinicalRouteDecision,
) -> list[str]:
    if route_decision.primary_route != "organic_acids_route":
        return []
    err: list[str] = []
    low = (report_text or "").lower()
    if "цистит" in low and "органическ" in low:
        err.append("report_may_mix_uti_with_oa")
    return err
