from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.master_route_loader import list_master_routes, run_master_route
from app.services.symptom_route_detector import detect_symptom_routes


MASTER_ROUTE_IDS = set(list_master_routes())


@dataclass
class UnifiedMasterRoutingResult:
    selected_route_id: str | None
    confidence: float
    reasons: list[str]
    payload: dict[str, Any]


class UnifiedMasterRouter:
    def classify(self, *, user_text: str, symptoms: list[str] | None = None) -> dict[str, Any]:
        matches = detect_symptom_routes(user_text, symptoms or [])
        master_matches = [m for m in matches if str(m.get("route_id")) in MASTER_ROUTE_IDS]
        if not master_matches:
            return {"selected_route_id": None, "confidence": 0.0, "reasons": ["no_master_route_match"], "matches": []}

        top = master_matches[0]
        return {
            "selected_route_id": str(top.get("route_id")),
            "confidence": float(top.get("confidence") or 0.0),
            "reasons": [str(top.get("reason") or "symptom_master_match")],
            "matches": master_matches,
        }

    def route(
        self,
        *,
        user_text: str,
        symptoms: list[str] | None = None,
        recurrent: bool = False,
        preferred_route_id: str | None = None,
    ) -> UnifiedMasterRoutingResult:
        selected_route = preferred_route_id if preferred_route_id in MASTER_ROUTE_IDS else None
        classify_data: dict[str, Any] = {}
        if not selected_route:
            classify_data = self.classify(user_text=user_text, symptoms=symptoms)
            selected_route = str(classify_data.get("selected_route_id") or "") or None

        if not selected_route:
            return UnifiedMasterRoutingResult(
                selected_route_id=None,
                confidence=float(classify_data.get("confidence") or 0.0),
                reasons=list(classify_data.get("reasons") or ["no_master_route_match"]),
                payload={},
            )

        route_payload = run_master_route(
            route_id=selected_route,
            message=user_text,
            recurrent=recurrent,
            cause_limit=4,
        )
        reasons = list(classify_data.get("reasons") or [])
        if preferred_route_id and preferred_route_id == selected_route:
            reasons.append("preferred_route_override")
        if not reasons:
            reasons.append("master_route_selected")

        return UnifiedMasterRoutingResult(
            selected_route_id=selected_route,
            confidence=float(classify_data.get("confidence") or 0.0),
            reasons=reasons,
            payload=route_payload,
        )
