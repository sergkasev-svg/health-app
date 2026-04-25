"""
Расчёт скоринга по осям Microbiome Engine v1.
Простая модель: age, low_activity, fatigue, poor_diet → 0–2 низкий, 3–5 средний, 6+ высокий.
"""
from __future__ import annotations

from typing import Any

from app.services.microbiome_engine.config import AXIS_TRIGGERS, GUT_MUSCLE_AGE_THRESHOLD


def calc_axis_score(inputs: dict[str, Any]) -> int:
    """
    Суммарный балл риска по входам.
    inputs: age (int|None), low_activity (bool), fatigue (bool), poor_diet (bool).
    Каждый фактор 0–2 балла.
    """
    score = 0
    age = inputs.get("age")
    if age is not None and isinstance(age, (int, float)):
        if int(age) > 50:
            score += 2
    if inputs.get("low_activity"):
        score += 2
    if inputs.get("fatigue"):
        score += 2
    if inputs.get("poor_diet"):
        score += 2
    return min(score, 10)


def score_to_level(score: int) -> str:
    """0–2: низкий, 3–5: средний, 6+: высокий."""
    if score <= 2:
        return "low"
    if score <= 5:
        return "moderate"
    return "high"


def detect_active_axes(
    text: str,
    age: int | None = None,
) -> list[str]:
    """
    По тексту (симптомы/жалобы) и опционально возрасту возвращает список активных осей.
    """
    if not text or not text.strip():
        if age is not None and age >= GUT_MUSCLE_AGE_THRESHOLD:
            return ["gut_muscle"]
        return []
    low = text.strip().lower()
    active: list[str] = []
    for axis, triggers in AXIS_TRIGGERS.items():
        if any(t in low for t in triggers):
            active.append(axis)
    if "gut_muscle" not in active and age is not None and age >= GUT_MUSCLE_AGE_THRESHOLD:
        active.append("gut_muscle")
    return list(dict.fromkeys(active))  # preserve order, no dupes
