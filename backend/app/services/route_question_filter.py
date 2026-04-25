"""
Фильтрация уточняющих вопросов по маршруту.
"""
from __future__ import annotations

import re

from app.services.clinical_routing_models import ClinicalRouteDecision

_ORGANIC_ACIDS_FORBIDDEN_Q = re.compile(
    r"фасол|бобов|вин[оа]|шоколад|цитрус|сыр|творог|кефир|йогурт|молочн",
    re.I,
)

_THYROID_FORBIDDEN_Q = re.compile(
    r"мочеиспуск|цистит|жжение\s+при\s+моче|дизури",
    re.I,
)

_CBC_FORBIDDEN_Q = re.compile(
    r"ттг|tsh|щитовид|тирео",
    re.I,
)

_FOOD_TRIGGER_Q = re.compile(
    r"вино|шоколад|сыр|творог|фасол|цитрус|копчен|ферментир",
    re.I,
)


def filter_questions_by_route(
    questions: list[str],
    route_decision: ClinicalRouteDecision,
) -> list[str]:
    if not questions:
        return []
    pr = route_decision.primary_route
    sec = set(route_decision.secondary_routes or [])
    allow_food = "allergy_route" in sec or pr == "allergy_route"

    out: list[str] = []
    for q in questions:
        s = str(q or "").strip()
        if not s:
            continue
        if pr == "organic_acids_route" and _ORGANIC_ACIDS_FORBIDDEN_Q.search(s):
            continue
        if pr == "thyroid_route" and _THYROID_FORBIDDEN_Q.search(s):
            continue
        if pr == "cbc_route" and _CBC_FORBIDDEN_Q.search(s):
            continue
        if not allow_food and _FOOD_TRIGGER_Q.search(s):
            continue
        out.append(s)
    return out[:3]
