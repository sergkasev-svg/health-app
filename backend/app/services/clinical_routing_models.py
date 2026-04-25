"""
Модели слоя Clinical Routing Engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ClinicalRouteMatch:
    route_id: str
    confidence: float
    source: str
    reasons: list[str] = field(default_factory=list)
    blocked_routes: list[str] = field(default_factory=list)


@dataclass
class ClinicalRouteContext:
    input_type: str | None = None
    detected_document_types: list[str] = field(default_factory=list)
    detected_lab_types: list[str] = field(default_factory=list)
    detected_symptom_groups: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass
class ClinicalRouteDecision:
    primary_route: str
    secondary_routes: list[str] = field(default_factory=list)
    blocked_routes: list[str] = field(default_factory=list)
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    safety_override: bool = False
    debug: dict[str, Any] = field(default_factory=dict)

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "primary_route": self.primary_route,
            "secondary_routes": list(self.secondary_routes),
            "blocked_routes": list(self.blocked_routes),
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "safety_override": self.safety_override,
        }
