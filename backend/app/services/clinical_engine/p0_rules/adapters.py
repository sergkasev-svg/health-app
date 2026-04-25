"""
Адаптеры: существующие экстракторы → Dict[str, MarkerSnapshot] для P0 rules.
"""
from __future__ import annotations

from typing import Any, Dict, List, TYPE_CHECKING

from app.services.clinical_engine.p0_rules.contract import MarkerSnapshot

if TYPE_CHECKING:
    from app.services.lab_value_extractor import LabValue


# Соответствие marker из extract_cbc_values → канонический код правил
_CBC_MARKER_MAP = {
    "Hb": "hb",
    "RBC": "rbc",
    "Hct": "hct",
    "MCV": "mcv",
    "MCH": "mch",
    "MCHC": "mchc",
    "RDW": "rdw",
    "WBC": "wbc",
    "PLT": "plt",
    "ESR": "esr",
    "Neutrophils": "neutrophils_pct",
    "Lymphocytes": "lymphocytes_pct",
    "Monocytes": "monocytes_pct",
    "Eosinophils": "eosinophils_pct",
    "Basophils": "basophils_pct",
    "Reticulocytes": "reticulocytes_pct",
    "Reticulocytes_rel": "reticulocytes_pct",
    "Reticulocytes_abs": "reticulocytes_abs",
}


def _lv_to_snapshot(lv: "LabValue") -> MarkerSnapshot:
    return MarkerSnapshot(
        value=lv.value,
        ref_low=lv.ref_low,
        ref_high=lv.ref_high,
        value_text=None,
        status=lv.status,
    )


def labvalues_to_cbc_map(rows: List["LabValue"]) -> Dict[str, MarkerSnapshot]:
    """List[LabValue] из extract_cbc_values → словарь для CBC rules."""
    out: Dict[str, MarkerSnapshot] = {}
    for lv in rows:
        key = _CBC_MARKER_MAP.get(lv.marker)
        if not key:
            continue
        if key not in out:
            out[key] = _lv_to_snapshot(lv)
    return out


# Коды urinalysis_engine
_URINE_ENGINE_MAP = {
    "urine_ph": "ph",
    "urine_specific_gravity": "specific_gravity",
    "urine_protein": "protein",
    "urine_glucose": "glucose",
    "urine_ketones": "ketones",
    "urine_blood": "blood_reaction",
    "urine_nitrites": "nitrites",
    "urine_leukocytes": "leukocytes",
    "urine_erythrocytes": "erythrocytes",
    "urine_bacteria": "bacteria",
}


def urinalysis_dict_to_map(engine_dict: Dict[str, Dict[str, Any]]) -> Dict[str, MarkerSnapshot]:
    """Результат extract_urine_values из urinalysis_engine."""
    out: Dict[str, MarkerSnapshot] = {}
    for eng_key, snap_key in _URINE_ENGINE_MAP.items():
        raw = engine_dict.get(eng_key)
        if not raw:
            continue
        out[snap_key] = MarkerSnapshot(
            value=raw.get("value") if isinstance(raw.get("value"), (int, float)) else None,
            ref_low=raw.get("ref_low") if isinstance(raw.get("ref_low"), (int, float)) else None,
            ref_high=raw.get("ref_high") if isinstance(raw.get("ref_high"), (int, float)) else None,
            value_text=str(raw.get("value_text") or "") or None,
            status=raw.get("status"),
        )
    return out


def dict_floats_to_map(data: Dict[str, Any]) -> Dict[str, MarkerSnapshot]:
    """Тесты / ручной ввод: {"hb": {"value": 120, "ref_low": 120, "ref_high": 160}}."""
    out: Dict[str, MarkerSnapshot] = {}
    for k, v in (data or {}).items():
        if isinstance(v, MarkerSnapshot):
            out[k] = v
        elif isinstance(v, dict):
            out[k] = MarkerSnapshot(
                value=v.get("value"),
                ref_low=v.get("ref_low"),
                ref_high=v.get("ref_high"),
                value_text=v.get("value_text"),
                status=v.get("status"),
            )
    return out
