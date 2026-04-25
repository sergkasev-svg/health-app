"""Сценарии усталости / астении v2 — medical_knowledge/diseases/fatigue_scenarios_v2.json."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.scenario_v2_common import build_structured_v2_payload, format_appendix_from_scenario_row

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_SCENARIO_FILE = _PROJECT_ROOT / "medical_knowledge" / "diseases" / "fatigue_scenarios_v2.json"

COMPLAINT_ID_TO_SCENARIO_ID: dict[str, str] = {
    "complaint_chronic_fatigue_months_no_recovery": "chronic_fatigue_after_sleep",
    "complaint_adolescent_anhedonia_apathy": "teen_fatigue_school_brainfog",
    "complaint_lab_indices_oncophobia": "fear_of_cancer_due_to_lymphocytes",
    "complaint_postpartum_distress": "postpartum_crying_apathy",
    "complaint_health_anxiety_mortality_fear": "fear_of_serious_illness_death",
    "complaint_prolonged_loss_of_appetite": "loss_of_appetite_two_months",
    "complaint_knee_postinjury_training_return": "post_injury_training_plateau",
}


@lru_cache(maxsize=1)
def load_fatigue_scenarios_bundle() -> dict[str, Any]:
    if not _SCENARIO_FILE.is_file():
        return {"version": "", "category": "fatigue", "scenarios": []}
    try:
        data = json.loads(_SCENARIO_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"version": "", "category": "fatigue", "scenarios": []}
        if not isinstance(data.get("scenarios"), list):
            data["scenarios"] = []
        return data
    except Exception:
        return {"version": "", "category": "fatigue", "scenarios": []}


def list_fatigue_scenarios() -> list[dict[str, Any]]:
    return [x for x in (load_fatigue_scenarios_bundle().get("scenarios") or []) if isinstance(x, dict)]


def _indexes() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_pat: dict[str, dict[str, Any]] = {}
    for row in list_fatigue_scenarios():
        sid = str(row.get("scenario_id") or "").strip()
        if sid:
            by_id[sid] = row
        pid = str(row.get("pattern_id") or "").strip()
        if pid:
            by_pat[pid] = row
    return by_id, by_pat


def get_fatigue_scenario_by_id(scenario_id: str) -> dict[str, Any] | None:
    sid = (scenario_id or "").strip()
    if not sid:
        return None
    by_id, _ = _indexes()
    r = by_id.get(sid)
    return dict(r) if r else None


def get_fatigue_scenario_for_complaint_id(complaint_id: str) -> dict[str, Any] | None:
    cid = (complaint_id or "").strip()
    mapped = COMPLAINT_ID_TO_SCENARIO_ID.get(cid)
    if not mapped:
        return None
    return get_fatigue_scenario_by_id(mapped)


def format_fatigue_appendix_for_complaint(complaint_id: str) -> str:
    fh = get_fatigue_scenario_for_complaint_id((complaint_id or "").strip())
    return format_appendix_from_scenario_row(fh)


def fatigue_extra_structured(complaint_id: str) -> dict[str, Any] | None:
    fh = get_fatigue_scenario_for_complaint_id((complaint_id or "").strip())
    if not fh:
        return None
    b = load_fatigue_scenarios_bundle()
    return build_structured_v2_payload(
        fh,
        bundle_version=str(b.get("version") or ""),
        bundle_locale=b.get("locale"),
        bundle_category=b.get("category"),
        data_source="fatigue_scenarios_v2",
    )


def fatigue_bundle_version() -> str:
    return str(load_fatigue_scenarios_bundle().get("version") or "").strip()


__all__ = [
    "COMPLAINT_ID_TO_SCENARIO_ID",
    "fatigue_bundle_version",
    "fatigue_extra_structured",
    "format_fatigue_appendix_for_complaint",
    "get_fatigue_scenario_by_id",
    "get_fatigue_scenario_for_complaint_id",
    "list_fatigue_scenarios",
    "load_fatigue_scenarios_bundle",
]
