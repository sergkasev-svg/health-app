"""
Общие helper-функции для P0 rules (без дублирования в renderer).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.clinical_engine.p0_rules.contract import MarkerSnapshot


def has_finding(findings: List[Dict[str, Any]], code: str) -> bool:
    return any(f.get("code") == code for f in findings)


def get_marker(values: Dict[str, MarkerSnapshot], code: str) -> Optional[MarkerSnapshot]:
    return values.get(code)


def is_positive_qualitative(values: Dict[str, MarkerSnapshot], code: str) -> bool:
    """Положительный качественный тест мочи и т.п. (не отрицательно / не обнаружено)."""
    v = values.get(code)
    if v is None:
        return False
    if v.value is not None and v.value > 0:
        return True
    text = str(v.value_text or "").strip().lower()
    if not text:
        return False
    neg = (
        "",
        "0",
        "0.0",
        "отрицательно",
        "отриц",
        "не обнаружено",
        "negative",
        "neg",
        "trace",
    )
    if text in neg:
        return False
    if "положительно" in text or "positive" in text:
        return True
    return False


def numeric_or_positive(values: Dict[str, MarkerSnapshot], code: str) -> bool:
    """Число > 0 или положительный качественный."""
    v = values.get(code)
    if v is None:
        return False
    if v.value is not None:
        return v.value > 0
    return is_positive_qualitative(values, code)


def finding_codes(findings: List[Dict[str, Any]]) -> List[str]:
    return [str(f.get("code", "")) for f in findings if f.get("code")]
