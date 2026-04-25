"""
Извлечение антропометрии и витальных показателей из текста документа.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class VitalsSnapshot:
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    sbp_mmhg: Optional[float] = None
    dbp_mmhg: Optional[float] = None
    heart_rate: Optional[float] = None


def extract_vitals_from_text(text: str) -> VitalsSnapshot:
    if not text:
        return VitalsSnapshot()
    low = text.lower()
    h = _first_float(r"(?:рост|height)[^\d]{0,12}(\d{2,3})\s*(?:см|cm)?", text, low)
    w = _first_float(r"(?:вес|weight|масса)[^\d]{0,12}(\d{2,3}(?:[.,]\d)?)\s*(?:кг|kg)?", text, low)
    # АД 104/67 или 104 / 67
    bp = re.search(r"(?:ад|артериальн|давлен)[^\d]{0,20}(\d{2,3})\s*/\s*(\d{2,3})", low)
    sbp, dbp = (float(bp.group(1)), float(bp.group(2))) if bp else (None, None)
    if sbp is None:
        bp2 = re.search(r"\b(\d{2,3})\s*/\s*(\d{2,3})\b", text)
        if bp2:
            a, b = float(bp2.group(1)), float(bp2.group(2))
            if 60 <= a <= 220 and 40 <= b <= 140:
                sbp, dbp = a, b
    hr = _first_float(r"(?:чсс|чсс|пульс|heart\s*rate|hr)[^\d]{0,12}(\d{2,3})\b", text, low)
    if hr is None:
        hr = _first_float(r"(?:^|\s)(\d{2,3})\s*(?:уд/мин|уд\.?\s*мин|bpm)\b", text, low)
    return VitalsSnapshot(height_cm=h, weight_kg=w, sbp_mmhg=sbp, dbp_mmhg=dbp, heart_rate=hr)


def _first_float(pattern: str, text: str, low: str) -> Optional[float]:
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        m = re.search(pattern, low)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except (ValueError, IndexError):
        return None
