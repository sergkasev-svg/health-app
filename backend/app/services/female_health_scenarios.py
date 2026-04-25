"""Загрузка расширенных сценариев female_health.

При наличии файла ``female_health_scenarios_v2.json`` он используется вместо ``female_health_scenarios.json``.
Версия и расширенные поля (risk_level, routing, confidence_rules и т.д.) читаются из JSON без жёсткой схемы."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.scenario_v2_common import (
    build_structured_v2_payload,
    format_appendix_from_scenario_row,
    lab_codes_to_ru_labels,
)

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_SCENARIO_FILE_V1 = _PROJECT_ROOT / "medical_knowledge" / "diseases" / "female_health_scenarios.json"
_SCENARIO_FILE_V2 = _PROJECT_ROOT / "medical_knowledge" / "diseases" / "female_health_scenarios_v2.json"


def _active_scenario_json_path() -> Path:
    return _SCENARIO_FILE_V2 if _SCENARIO_FILE_V2.is_file() else _SCENARIO_FILE_V1


# Связка с карточками complaint_scenarios_short / детекторами complaint_reference.py
COMPLAINT_ID_TO_SCENARIO_ID: dict[str, str] = {
    "complaint_premenstrual_mood_sweet_craving": "pms_mood_cravings",
    "complaint_irregular_menstrual_cycle_women": "irregular_cycle",
    "complaint_acne_skin_hormonal_women": "acne_hormonal",
    "complaint_weight_plateau_women": "weight_not_losing",
    "complaint_hair_loss_diffuse_women": "hair_loss_female",
    "complaint_persistent_fatigue_women": "female_fatigue_general",
    "complaint_low_mood_apathy_women": "female_low_mood_apathy",
    "complaint_edema_swelling_women": "female_edema_cycle",
    "complaint_painful_periods_dysmenorrhea_women": "painful_menses",
    "complaint_sweet_craving_standalone_women": "sweet_cravings_female",
    "complaint_heavy_menstrual_bleeding_fatigue_hair_loss": "heavy_menses_fatigue_hairloss",
}


def format_female_health_appendix_for_complaint(
    complaint_id: str,
    *,
    max_questions: int = 3,
    max_labs: int = 5,
    max_flags: int = 3,
) -> str:
    """Короткий блок для чата после канонического первого ответа (без дублирования основного текста)."""
    fh = get_female_health_scenario_for_complaint_id((complaint_id or "").strip())
    return format_appendix_from_scenario_row(fh, max_questions=max_questions, max_labs=max_labs, max_flags=max_flags)


def female_health_extra_structured(complaint_id: str) -> dict[str, Any] | None:
    """Данные для поля structured в API при совпадении с female_health_scenarios."""
    cid = (complaint_id or "").strip()
    fh = get_female_health_scenario_for_complaint_id(cid)
    if not fh:
        return None
    bundle = load_female_health_scenarios_bundle()
    payload = build_structured_v2_payload(
        fh,
        bundle_version=str(bundle.get("version") or ""),
        bundle_locale=bundle.get("locale"),
        bundle_category=bundle.get("category"),
        data_source="female_health_scenarios_v2" if _SCENARIO_FILE_V2.is_file() else "female_health_scenarios_v1",
    )
    return payload


@lru_cache(maxsize=1)
def load_female_health_scenarios_bundle() -> dict[str, Any]:
    """Полный JSON-пакет (version, category, scenarios). При ошибке — пустая оболочка."""
    path = _active_scenario_json_path()
    if not path.is_file():
        return {"version": "", "category": "female_health", "scenarios": []}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {"version": "", "category": "female_health", "scenarios": []}
        scenarios = data.get("scenarios")
        if not isinstance(scenarios, list):
            data["scenarios"] = []
        return data
    except Exception:
        return {"version": "", "category": "female_health", "scenarios": []}


def list_female_health_scenarios() -> list[dict[str, Any]]:
    bundle = load_female_health_scenarios_bundle()
    out = bundle.get("scenarios") or []
    return [x for x in out if isinstance(x, dict)]


def _scenario_indexes() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_pattern: dict[str, dict[str, Any]] = {}
    for row in list_female_health_scenarios():
        sid = str(row.get("scenario_id") or "").strip()
        if sid:
            by_id[sid] = row
        pid = str(row.get("pattern_id") or "").strip()
        if pid:
            by_pattern[pid] = row
    return by_id, by_pattern


def get_female_health_scenario_by_id(scenario_id: str) -> dict[str, Any] | None:
    sid = (scenario_id or "").strip()
    if not sid:
        return None
    by_id, _ = _scenario_indexes()
    row = by_id.get(sid)
    return dict(row) if row else None


def get_female_health_scenario_by_pattern_id(pattern_id: str) -> dict[str, Any] | None:
    pid = (pattern_id or "").strip()
    if not pid:
        return None
    _, by_pattern = _scenario_indexes()
    row = by_pattern.get(pid)
    return dict(row) if row else None


def get_female_health_scenario_for_complaint_id(complaint_id: str) -> dict[str, Any] | None:
    """Сценарий из JSON по id карточки жалобы (complaint_*)."""
    cid = (complaint_id or "").strip()
    sid = COMPLAINT_ID_TO_SCENARIO_ID.get(cid)
    if not sid:
        return None
    return get_female_health_scenario_by_id(sid)


def female_health_bundle_version() -> str:
    return str(load_female_health_scenarios_bundle().get("version") or "").strip()
