"""Runtime routing control config for offline/OpenAI strategy."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_QUALITY_DIR = _BACKEND_DIR / "data" / "quality"
_CONFIG_FILE = _QUALITY_DIR / "routing_control.json"

DEFAULT_CONFIG = {
    "offline_first_enabled": True,
    "top_complaints_limit": 40,
    "max_offline_first_user_turns": 1,
    "season_weight_multiplier": 1.0,
    "demand_weight_multiplier": 1.0,
    "use_unified_master_router": False,
    "unified_master_min_confidence": 0.72,
}


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_routing_control_config() -> dict[str, Any]:
    data = _read_json(_CONFIG_FILE)
    out = dict(DEFAULT_CONFIG)
    out.update({k: data.get(k) for k in DEFAULT_CONFIG.keys() if k in data})
    try:
        out["top_complaints_limit"] = max(5, min(int(out.get("top_complaints_limit") or 40), 100))
    except Exception:
        out["top_complaints_limit"] = 40
    try:
        out["max_offline_first_user_turns"] = max(0, min(int(out.get("max_offline_first_user_turns") or 1), 5))
    except Exception:
        out["max_offline_first_user_turns"] = 1
    for key in ("season_weight_multiplier", "demand_weight_multiplier"):
        try:
            out[key] = max(0.0, min(float(out.get(key) or 1.0), 5.0))
        except Exception:
            out[key] = 1.0
    try:
        out["unified_master_min_confidence"] = max(
            0.0,
            min(float(out.get("unified_master_min_confidence") or 0.72), 1.0),
        )
    except Exception:
        out["unified_master_min_confidence"] = 0.72
    out["offline_first_enabled"] = bool(out.get("offline_first_enabled"))
    out["use_unified_master_router"] = bool(out.get("use_unified_master_router"))
    return out


def update_routing_control_config(payload: dict[str, Any]) -> dict[str, Any]:
    current = dict(get_routing_control_config())
    for key in DEFAULT_CONFIG.keys():
        if key in payload:
            current[key] = payload[key]
    _write_json(_CONFIG_FILE, current)
    return get_routing_control_config()


def detect_specialized_branch(text: str, medical_relevance_filter: Any | None = None) -> str | None:
    """Best-effort specialized branch detection (soft, non-breaking)."""
    cfg = get_routing_control_config()
    food_score = 0.0
    if medical_relevance_filter is not None and hasattr(medical_relevance_filter, "score_food_branch_relevance"):
        try:
            food_score = float(medical_relevance_filter.score_food_branch_relevance(text))
        except Exception:
            food_score = 0.0
    if food_score >= 0.33:
        return "food_postmeal_branch"
    if cfg.get("use_unified_master_router"):
        try:
            from app.services.unified_master_router import UnifiedMasterRouter

            match = UnifiedMasterRouter().classify(user_text=text, symptoms=[])
            route_id = str(match.get("selected_route_id") or "").strip()
            confidence = float(match.get("confidence") or 0.0)
            if route_id and confidence >= float(cfg.get("unified_master_min_confidence") or 0.72):
                return route_id
        except Exception:
            return None
    return None
