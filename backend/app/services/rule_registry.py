from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RuleRegistry:
    """
    Central registry for reusable rule groups.
    Helps scale from food branch to other branches later.
    """

    super_master: dict[str, Any]
    routing: dict[str, Any]
    templates: dict[str, Any]

    def get_zone_rules(self) -> list[dict[str, Any]]:
        return list(self.routing.get("zone_rules", []))

    def get_cluster_rules(self) -> list[dict[str, Any]]:
        return list(self.routing.get("cluster_rules", []))

    def get_templates(self) -> dict[str, Any]:
        return dict(self.templates.get("templates", {}))

    def get_causes(self) -> list[dict[str, Any]]:
        return list(self.super_master.get("causes", []))

    def get_red_flags(self) -> list[str]:
        return list(self.routing.get("red_flag_rules", {}).get("match_any", []))

    def get_tests_rules(self) -> list[dict[str, Any]]:
        return list(self.routing.get("tests_rules", []))

