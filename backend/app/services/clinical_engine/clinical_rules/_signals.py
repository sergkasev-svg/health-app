"""Общие проверки статусов LabValue для правил P1/P2."""
from __future__ import annotations

from typing import Optional

from app.services.clinical_engine.contracts import LabValue


def value_is_low(v: Optional[LabValue]) -> bool:
    if not v or v.value is None:
        return False
    st = (v.status or "").lower()
    if "low" in st and "high" not in st:
        return True
    if v.ref_low is not None and float(v.value) < float(v.ref_low):
        return True
    return False


def value_is_high(v: Optional[LabValue]) -> bool:
    if not v or v.value is None:
        return False
    st = (v.status or "").lower()
    if "high" in st or "significant_high" in st:
        return True
    if v.ref_high is not None and float(v.value) > float(v.ref_high):
        return True
    return False


def value_is_normal(v: Optional[LabValue]) -> bool:
    if not v or v.value is None:
        return False
    st = (v.status or "").lower()
    if st == "normal":
        return True
    if v.ref_low is not None and v.ref_high is not None:
        lo, hi = float(v.ref_low), float(v.ref_high)
        x = float(v.value)
        return lo <= x <= hi
    return False


def value_is_borderline_low(v: Optional[LabValue]) -> bool:
    if not v or v.value is None:
        return False
    return "borderline_low" in (v.status or "").lower()
