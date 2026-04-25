"""
Фильтрация гипотез по primary_route (authoritative document route).
"""
from __future__ import annotations

import re
from typing import Any

from app.services.clinical_routing_models import ClinicalRouteDecision
from app.services.clinical_route_registry import get_route_spec

# Подстроки в названии гипотезы → блок для маршрута
_ORGANIC_ACIDS_BLOCKED = [
    "цистит", "пиелонефрит", "мочевывод",
    "гистамин", "histamine", "аллерг", "мигрен", "migraine",
    "пищев", "food allergy", "инфекц", "липид", "холестер", "ттг", "щитовид",
]

_CBC_BLOCKED = ["липид", "холестер", "лпнп", "organic", "органическ", "ттг", "щитовид"]

_THYROID_BLOCKED = ["цистит", "пиелонефрит", "мочев", "ути"]


def _blocked_for_route(primary_route: str) -> list[str]:
    if primary_route == "organic_acids_route":
        return _ORGANIC_ACIDS_BLOCKED
    if primary_route == "cbc_route":
        return _CBC_BLOCKED
    if primary_route == "thyroid_route":
        return _THYROID_BLOCKED
    if primary_route == "lipid_route":
        return ["цистит", "пиелонефрит", "органическ", "гистамин", "анемия", "железодефицит"]
    if primary_route == "urine_general_route":
        return ["органическ", "гх-мс", "липид", "ттг"]
    spec = get_route_spec(primary_route)
    if not spec:
        return []
    # минимальный fallback по тегам
    return []


def filter_hypotheses_by_route(
    hypotheses: list[dict[str, Any]],
    route_decision: ClinicalRouteDecision,
) -> list[dict[str, Any]]:
    if not hypotheses:
        return []
    pr = route_decision.primary_route
    if pr in ("emergency_route", "generic_safe_route", "physician_report_only_route"):
        return hypotheses[:3]

    blocked_subs = [s.lower() for s in _blocked_for_route(pr)]
    out: list[dict[str, Any]] = []
    for h in hypotheses:
        name = str(h.get("name") or h.get("title") or "").lower()
        if not name:
            continue
        if any(b in name for b in blocked_subs):
            continue
        out.append(h)
    return out[:3]


def user_hypothesis_strings(filtered: list[dict[str, Any]], max_n: int = 2) -> list[str]:
    return [
        str(h.get("name") or h.get("title") or "").strip()
        for h in filtered[:max_n]
        if (h.get("name") or h.get("title"))
    ]
