"""
Medical knowledge search API. Isolated from existing user/chat logic.
Uses MedicalKnowledgeSearch; all responses include disclaimer.
"""
from pydantic import BaseModel, Field
from fastapi import APIRouter, Query

from app.services.complaint_reference import current_season_label, get_prioritized_complaints
from app.services.medical_knowledge_search import search
from app.services.routing_control import get_routing_control_config, update_routing_control_config

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


UNIFIED_MASTER_ROLLOUT_PRESETS: dict[str, dict[str, float | bool]] = {
    "off": {
        "use_unified_master_router": False,
        "unified_master_min_confidence": 0.72,
    },
    # Conservative pilot: enable only highly-confident matches.
    "pilot_strict": {
        "use_unified_master_router": True,
        "unified_master_min_confidence": 0.86,
    },
    "pilot_balanced": {
        "use_unified_master_router": True,
        "unified_master_min_confidence": 0.80,
    },
    "expanded_balanced": {
        "use_unified_master_router": True,
        "unified_master_min_confidence": 0.75,
    },
    "aggressive": {
        "use_unified_master_router": True,
        "unified_master_min_confidence": 0.70,
    },
}


class UnifiedMasterRoutingPatch(BaseModel):
    enabled: bool | None = Field(
        default=None,
        description="Enable unified master router feature-flag",
    )
    min_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence threshold for unified master route selection",
    )


def _unified_master_subset(cfg: dict) -> dict:
    out = {
        "use_unified_master_router": bool(cfg.get("use_unified_master_router")),
        "unified_master_min_confidence": float(cfg.get("unified_master_min_confidence") or 0.72),
    }
    out["rollout_mode"] = "enabled" if out["use_unified_master_router"] else "disabled"
    return out


@router.get("/search")
def knowledge_search(
    q: str = Query(..., min_length=1, description="Query, e.g. high cortisol, fatigue, anemia symptoms"),
    max_results: int = Query(10, ge=1, le=20),
    language: str = Query("", description="Preferred language code (e.g. ru, en)"),
):
    """Search ingested medical knowledge. Returns summary, possible causes, recommended tests, red flags. Not a diagnosis."""
    return search(query=q, max_results=max_results, language=language or "")


@router.get("/top-complaints")
def knowledge_top_complaints(
    limit: int = Query(20, ge=1, le=100),
    season: str = Query("", description="Season label: current, весна, лето, осень, зима"),
):
    selected_season = current_season_label() if not season or season == "current" else season
    cfg = get_routing_control_config()
    items = get_prioritized_complaints(
        limit=limit,
        season=selected_season,
        season_weight_multiplier=float(cfg.get("season_weight_multiplier") or 1.0),
        demand_weight_multiplier=float(cfg.get("demand_weight_multiplier") or 1.0),
    )
    return {
        "season": selected_season,
        "count": len(items),
        "items": items,
    }


@router.get("/routing-control")
def knowledge_routing_control_get():
    return get_routing_control_config()


@router.patch("/routing-control")
def knowledge_routing_control_patch(payload: dict):
    return update_routing_control_config(payload or {})


@router.get("/routing-control/unified-master")
def knowledge_unified_master_routing_get():
    cfg = get_routing_control_config()
    return {
        "routing_control": _unified_master_subset(cfg),
        "available_presets": list(UNIFIED_MASTER_ROLLOUT_PRESETS.keys()),
    }


@router.patch("/routing-control/unified-master")
def knowledge_unified_master_routing_patch(payload: UnifiedMasterRoutingPatch):
    updates: dict[str, float | bool] = {}
    if payload.enabled is not None:
        updates["use_unified_master_router"] = bool(payload.enabled)
    if payload.min_confidence is not None:
        updates["unified_master_min_confidence"] = float(payload.min_confidence)
    next_cfg = update_routing_control_config(updates)
    return {
        "routing_control": _unified_master_subset(next_cfg),
        "updated_fields": list(updates.keys()),
    }


@router.post("/routing-control/unified-master/presets/{preset_id}")
def knowledge_unified_master_routing_apply_preset(preset_id: str):
    preset = UNIFIED_MASTER_ROLLOUT_PRESETS.get((preset_id or "").strip().lower())
    if not preset:
        return {
            "ok": False,
            "error": "unknown_preset",
            "allowed_presets": list(UNIFIED_MASTER_ROLLOUT_PRESETS.keys()),
        }
    next_cfg = update_routing_control_config(dict(preset))
    return {
        "ok": True,
        "preset_id": preset_id,
        "routing_control": _unified_master_subset(next_cfg),
    }
