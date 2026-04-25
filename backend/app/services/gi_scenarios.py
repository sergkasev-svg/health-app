"""Сценарии ЖКТ v2 — medical_knowledge/diseases/gi_scenarios_v2.json."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.scenario_v2_common import build_structured_v2_payload, format_appendix_from_scenario_row

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_SCENARIO_FILE = _PROJECT_ROOT / "medical_knowledge" / "diseases" / "gi_scenarios_v2.json"

COMPLAINT_ID_TO_SCENARIO_ID: dict[str, str] = {
    "complaint_gas_bloating": "bloating_gas_digestive_discomfort",
    "complaint_heartburn": "heartburn_reflux",
    "complaint_constipation": "constipation_long_term",
    "complaint_diarrhea": "diarrhea_acute",
    "complaint_nutrition_supplements_where_to_start": "food_supplements_starting_point",
}


@lru_cache(maxsize=1)
def load_gi_scenarios_bundle() -> dict[str, Any]:
    if not _SCENARIO_FILE.is_file():
        return {"version": "", "category": "gastrointestinal", "scenarios": []}
    try:
        data = json.loads(_SCENARIO_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"version": "", "category": "gastrointestinal", "scenarios": []}
        if not isinstance(data.get("scenarios"), list):
            data["scenarios"] = []
        return data
    except Exception:
        return {"version": "", "category": "gastrointestinal", "scenarios": []}


def list_gi_scenarios() -> list[dict[str, Any]]:
    return [x for x in (load_gi_scenarios_bundle().get("scenarios") or []) if isinstance(x, dict)]


def _indexes() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_pat: dict[str, dict[str, Any]] = {}
    for row in list_gi_scenarios():
        sid = str(row.get("scenario_id") or "").strip()
        if sid:
            by_id[sid] = row
        pid = str(row.get("pattern_id") or "").strip()
        if pid:
            by_pat[pid] = row
    return by_id, by_pat


def get_gi_scenario_by_id(scenario_id: str) -> dict[str, Any] | None:
    sid = (scenario_id or "").strip()
    if not sid:
        return None
    by_id, _ = _indexes()
    r = by_id.get(sid)
    return dict(r) if r else None


def get_gi_scenario_for_complaint_id(complaint_id: str) -> dict[str, Any] | None:
    cid = (complaint_id or "").strip()
    mapped = COMPLAINT_ID_TO_SCENARIO_ID.get(cid)
    if not mapped:
        return None
    return get_gi_scenario_by_id(mapped)


def format_gi_appendix_for_complaint(complaint_id: str) -> str:
    fh = get_gi_scenario_for_complaint_id((complaint_id or "").strip())
    return format_appendix_from_scenario_row(fh)


def gi_extra_structured(complaint_id: str) -> dict[str, Any] | None:
    fh = get_gi_scenario_for_complaint_id((complaint_id or "").strip())
    if not fh:
        return None
    b = load_gi_scenarios_bundle()
    return build_structured_v2_payload(
        fh,
        bundle_version=str(b.get("version") or ""),
        bundle_locale=b.get("locale"),
        bundle_category=b.get("category"),
        data_source="gi_scenarios_v2",
    )


def gi_bundle_version() -> str:
    return str(load_gi_scenarios_bundle().get("version") or "").strip()


__all__ = [
    "COMPLAINT_ID_TO_SCENARIO_ID",
    "format_gi_appendix_for_complaint",
    "get_gi_scenario_by_id",
    "get_gi_scenario_for_complaint_id",
    "gi_bundle_version",
    "gi_extra_structured",
    "list_gi_scenarios",
    "load_gi_scenarios_bundle",
]
