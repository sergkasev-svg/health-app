"""
Коррекции формулировок для пациентов < 18 лет: без жёстких «взрослых» ярлыков ССР по одному бланку.
"""
from __future__ import annotations

import re
from typing import Any, Dict


def is_pediatric(patient_meta: Dict[str, Any]) -> bool:
    age = patient_meta.get("age_years")
    if age is None:
        return False
    try:
        return float(age) < 18.0
    except (TypeError, ValueError):
        return False


def soften_adult_risk_phrasing(text: str) -> str:
    """Смягчает автоматические формулировки высокого ССР-риска для детей/подростков."""
    if not text:
        return text
    t = text
    repl = (
        (r"высокий\s+сердечно-сосудистый\s+риск", "неблагоприятный липидный профиль (требует оценки врача)"),
        (r"высокий\s+кардиоваскулярный\s+риск", "неблагоприятный липидный профиль (требует оценки врача)"),
        (r"атеросклероз", "нарушение липидного обмена (оценка врача)"),
    )
    for pat, sub in repl:
        t = re.sub(pat, sub, t, flags=re.IGNORECASE)
    return t


def lower_confidence_for_adult_labels(confidence: float) -> float:
    """Небольшое снижение уверенности для авто-ярлыков, если бы применялись к детям."""
    return max(0.5, confidence - 0.05)


def apply_pediatric_tone_to_summary(summary: str, patient_meta: Dict[str, Any]) -> str:
    if not is_pediatric(patient_meta):
        return summary
    return soften_adult_risk_phrasing(summary)
