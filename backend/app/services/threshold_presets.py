"""Preset bundles for routing and release gate policies."""
from __future__ import annotations

from typing import Any

from app.services.release_gate_policy import update_release_gate_policy
from app.services.routing_control import update_routing_control_config

PRESETS: dict[str, dict[str, Any]] = {
    "safe": {
        "label": "Safe",
        "description": "Более строгий quality gate и осторожный offline-first.",
        "routing_control": {
            "offline_first_enabled": True,
            "top_complaints_limit": 30,
            "max_offline_first_user_turns": 1,
            "season_weight_multiplier": 1.1,
            "demand_weight_multiplier": 0.9,
        },
        "release_gate_policy": {
            "weak_core_quality_threshold": 50,
            "min_total_events_warn": 20,
            "llm_share_warn_threshold": 0.6,
        },
    },
    "balanced": {
        "label": "Balanced",
        "description": "Сбалансированный режим между качеством и стоимостью.",
        "routing_control": {
            "offline_first_enabled": True,
            "top_complaints_limit": 40,
            "max_offline_first_user_turns": 1,
            "season_weight_multiplier": 1.0,
            "demand_weight_multiplier": 1.0,
        },
        "release_gate_policy": {
            "weak_core_quality_threshold": 40,
            "min_total_events_warn": 10,
            "llm_share_warn_threshold": 0.8,
        },
    },
    "cost_saving": {
        "label": "Cost-saving",
        "description": "Более агрессивный offline-first и более мягкий release gate.",
        "routing_control": {
            "offline_first_enabled": True,
            "top_complaints_limit": 60,
            "max_offline_first_user_turns": 2,
            "season_weight_multiplier": 1.3,
            "demand_weight_multiplier": 1.2,
        },
        "release_gate_policy": {
            "weak_core_quality_threshold": 35,
            "min_total_events_warn": 8,
            "llm_share_warn_threshold": 0.9,
        },
    },
}


def list_threshold_presets() -> dict[str, Any]:
    return {"items": [{"id": k, **v} for k, v in PRESETS.items()]}


def apply_threshold_preset(preset_id: str) -> dict[str, Any]:
    key = str(preset_id or "").strip()
    preset = PRESETS.get(key)
    if not preset:
        raise ValueError("Unknown preset")
    routing = update_routing_control_config(dict(preset.get("routing_control") or {}))
    gate = update_release_gate_policy(dict(preset.get("release_gate_policy") or {}))
    return {
        "preset_id": key,
        "label": preset.get("label") or key,
        "routing_control": routing,
        "release_gate_policy": gate,
    }
