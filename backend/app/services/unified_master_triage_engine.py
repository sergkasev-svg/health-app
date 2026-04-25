from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.unified_master_router import UnifiedMasterRouter


@dataclass
class UnifiedMasterTriageOutput:
    matched: bool
    route_id: str | None
    confidence: float
    reasons: list[str]
    triage_payload: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "route_id": self.route_id,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "triage_payload": self.triage_payload,
        }


class UnifiedMasterTriageEngine:
    def __init__(self, router: UnifiedMasterRouter | None = None) -> None:
        self.router = router or UnifiedMasterRouter()

    def triage(
        self,
        *,
        user_text: str,
        symptoms: list[str] | None = None,
        recurrent: bool = False,
        preferred_route_id: str | None = None,
    ) -> UnifiedMasterTriageOutput:
        result = self.router.route(
            user_text=user_text,
            symptoms=symptoms or [],
            recurrent=recurrent,
            preferred_route_id=preferred_route_id,
        )
        return UnifiedMasterTriageOutput(
            matched=bool(result.selected_route_id and result.payload),
            route_id=result.selected_route_id,
            confidence=float(result.confidence),
            reasons=list(result.reasons),
            triage_payload=result.payload,
        )
