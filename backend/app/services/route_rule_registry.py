"""
Привязка rule sets к маршрутам (алиас к clinical_route_registry для явного импорта).
"""
from __future__ import annotations

from app.services.clinical_route_registry import ROUTES, RouteSpec, get_route_spec

__all__ = ["ROUTES", "RouteSpec", "get_route_spec", "rules_for_route"]


def rules_for_route(route_id: str) -> tuple[list[str], list[str]]:
    """(allowed_rule_sets, blocked_rule_sets) для маршрута."""
    spec = get_route_spec(route_id)
    if not spec:
        return [], []
    return list(spec.allowed_rule_sets), list(spec.blocked_rule_sets)
