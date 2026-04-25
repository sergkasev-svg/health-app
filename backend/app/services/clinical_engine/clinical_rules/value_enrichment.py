"""
Объединяет значения из основного extract_blood_biochemistry с ОАК/ферритином/vitD/non-HDL из текста.
Не перезаписывает уже извлечённые канонические коды (приоритет у pipeline).
"""
from __future__ import annotations

import re
from typing import Any, Dict

from app.services.clinical_engine.contracts import LabValue
from app.services.clinical_engine.extractor import extract_blood_biochemistry
from app.services.lab_value_extractor import extract_cbc_values

_CBC_CODE_MAP: Dict[str, str] = {
    "Hb": "hb",
    "Hct": "hct",
    "MCHC": "mchc",
    "MCV": "mcv",
    "WBC": "wbc",
    "ESR": "esr",
    "RBC": "rbc",
    "PLT": "plt",
}


def _status_from_cbc(status: str) -> str:
    s = (status or "").lower()
    if "low" in s or s in ("significant_low", "critical"):
        return "low"
    if "high" in s or s in ("significant_high", "critical") and "low" not in s:
        return "high"
    if "borderline_low" in s:
        return "borderline_low"
    if "borderline_high" in s:
        return "borderline_high"
    return "normal"


def _cbc_to_labvalue(canon: str, row: Any) -> LabValue:
    st = _status_from_cbc(row.status)
    return LabValue(
        code=canon,
        label=str(row.marker),
        value=float(row.value) if row.value is not None else None,
        unit=getattr(row, "unit", None) or "",
        ref_low=row.ref_low,
        ref_high=row.ref_high,
        ref_text=(
            f"{row.ref_low}–{row.ref_high}"
            if row.ref_low is not None and row.ref_high is not None
            else None
        ),
        status=st,
        source_text=(row.raw_line or "")[:200],
    )


def _parse_non_hdl(text: str) -> LabValue | None:
    low = text.lower()
    patterns = (
        r"non[\s\-]*hdl[\s:]*(\d+[,.]?\d*)",
        r"холестерин\s+не[\s\-]*лпвп[:\s]+(\d+[,.]?\d*)",
        r"nonhdl[\s:]*(\d+[,.]?\d*)",
    )
    for p in patterns:
        m = re.search(p, low)
        if m:
            try:
                val = float(m.group(1).replace(",", "."))
            except ValueError:
                continue
            ref_hi = 3.4
            st = "high" if val > ref_hi else "normal"
            return LabValue(
                code="non_hdl_cholesterol",
                label="non-HDL холестерин",
                value=val,
                unit="ммоль/л",
                ref_low=None,
                ref_high=ref_hi,
                status=st,
            )
    return None


def _parse_ferritin(text: str) -> LabValue | None:
    m = re.search(
        r"ферритин[:\s]+(\d+[,.]?\d*)\s*(?:нг/мл|ng/ml|мкг/л|µg/l|mcg/l)?",
        (text or "").lower(),
    )
    if not m:
        return None
    try:
        val = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    ref_lo, ref_hi = 15.0, 400.0
    st = "low" if val < ref_lo else "high" if val > ref_hi else "normal"
    return LabValue(
        code="ferritin",
        label="Ферритин",
        value=val,
        unit="нг/мл",
        ref_low=ref_lo,
        ref_high=ref_hi,
        status=st,
    )


def _parse_vitamin_d(text: str) -> LabValue | None:
    m = re.search(
        r"(?:25\s*[-–]?\s*oh|25\(oh\)|витамин\s*d)[^0-9]{0,40}(\d+[,.]?\d*)",
        (text or "").lower(),
    )
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    if not (5 < v < 200):
        return None
    ref_lo, ref_hi = 30.0, 100.0
    st = "low" if v < ref_lo else "high" if v > ref_hi else "normal"
    return LabValue(
        code="vitamin_d_25oh",
        label="25-OH витамин D",
        value=v,
        unit="нг/мл",
        ref_low=ref_lo,
        ref_high=ref_hi,
        status=st,
    )


def enrich_values_for_rules(
    base: Dict[str, LabValue],
    extracted_text: str,
) -> Dict[str, LabValue]:
    """Дополняет словарь значений для P1/P2; не затирает существующие коды."""
    out: Dict[str, LabValue] = dict(base or {})
    if not (extracted_text or "").strip():
        return out

    # HbA1c, CRP и др. из полного текста, если в base их не было (узкий lipid-only model)
    for v in extract_blood_biochemistry(extracted_text):
        if v.code not in out:
            out[v.code] = v

    for row in extract_cbc_values(extracted_text):
        code = _CBC_CODE_MAP.get(row.marker)
        if not code or code in out:
            continue
        out[code] = _cbc_to_labvalue(code, row)

    for parser in (_parse_non_hdl, _parse_ferritin, _parse_vitamin_d):
        lv = parser(extracted_text)
        if lv and lv.code not in out:
            out[lv.code] = lv

    return out
