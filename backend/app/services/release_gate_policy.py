"""Configurable release gate policy."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_QUALITY_DIR = _BACKEND_DIR / "data" / "quality"
_POLICY_FILE = _QUALITY_DIR / "release_gate_policy.json"

DEFAULT_POLICY = {
    "core_targets": ["Кашель", "Боль в горле", "Боль в животе", "Одышка", "Головная боль"],
    "weak_core_quality_threshold": 40,
    "min_total_events_warn": 10,
    "llm_share_warn_threshold": 0.8,
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


def get_release_gate_policy() -> dict[str, Any]:
    data = _read_json(_POLICY_FILE)
    out = dict(DEFAULT_POLICY)
    out.update({k: data.get(k) for k in DEFAULT_POLICY.keys() if k in data})
    out["core_targets"] = [str(x).strip() for x in (out.get("core_targets") or []) if str(x).strip()] or list(DEFAULT_POLICY["core_targets"])
    try:
        out["weak_core_quality_threshold"] = max(0, min(int(out.get("weak_core_quality_threshold") or 40), 100))
    except Exception:
        out["weak_core_quality_threshold"] = 40
    try:
        out["min_total_events_warn"] = max(1, min(int(out.get("min_total_events_warn") or 10), 10000))
    except Exception:
        out["min_total_events_warn"] = 10
    try:
        out["llm_share_warn_threshold"] = max(0.0, min(float(out.get("llm_share_warn_threshold") or 0.8), 1.0))
    except Exception:
        out["llm_share_warn_threshold"] = 0.8
    return out


def update_release_gate_policy(payload: dict[str, Any]) -> dict[str, Any]:
    current = dict(get_release_gate_policy())
    for key in DEFAULT_POLICY.keys():
        if key in payload:
            current[key] = payload[key]
    _write_json(_POLICY_FILE, current)
    return get_release_gate_policy()
