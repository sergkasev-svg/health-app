"""
Точка входа Microbiome Engine v1: symptoms, labs, lifestyle → risk_scores, insights, recommendations, upsell_hooks.
"""
from __future__ import annotations

from typing import Any

from app.services.microbiome_engine.config import (
    MICROBIOME_ENGINE_VERSION,
    AXES,
    ENTITIES,
)
from app.services.microbiome_engine.scoring import (
    calc_axis_score,
    score_to_level,
    detect_active_axes,
)
from app.services.microbiome_engine.insights import (
    generate_insights_for_axes,
    get_entities_for_axes,
)
from app.services.microbiome_engine.templates import (
    build_report_body,
    get_upsell_hook,
    AXIS_LABELS_RU,
    AXIS_EMOJI,
    DEFAULT_RECOMMENDATIONS,
)


def run_microbiome_engine(
    symptoms_text: str = "",
    age: int | None = None,
    low_activity: bool | None = None,
    poor_diet: bool | None = None,
    labs_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Запуск движка по входам (symptoms, lifestyle, опционально labs).
    Возвращает:
    - version, active
    - risk_scores: { total_score, level_ru, level }
    - active_axes: list[str]
    - axes_display: list[{ axis, label_ru, emoji }]
    - insights: list[insight]
    - recommendations: list[str]
    - report_body: str (готовый текст для пользователя)
    - upsell_hooks: list[dict]
    - entities: list (релевантные сущности)
    """
    # Определяем fatigue по тексту
    fatigue = False
    if symptoms_text and symptoms_text.strip():
        low = symptoms_text.strip().lower()
        fatigue = any(
            k in low
            for k in (
                "слабость",
                "усталость",
                "утомляемость",
                "нет сил",
                "сил нет",
                "снижение силы",
            )
        )

    inputs = {
        "age": age,
        "low_activity": bool(low_activity) if low_activity is not None else False,
        "fatigue": fatigue,
        "poor_diet": bool(poor_diet) if poor_diet is not None else False,
    }
    total_score = calc_axis_score(inputs)
    level = score_to_level(total_score)
    level_ru = {"low": "низкий", "moderate": "средний", "high": "высокий"}.get(level, "средний")

    active_axes = detect_active_axes(symptoms_text or "", age=age)
    # Если осей нет, но есть хотя бы один фактор риска — считаем gut_muscle по умолчанию при возрасте
    if not active_axes and (age is not None and age >= 50 or fatigue):
        active_axes = ["gut_muscle"]

    insights = generate_insights_for_axes(active_axes)
    entities = get_entities_for_axes(active_axes)
    report_body = build_report_body(active_axes, level, DEFAULT_RECOMMENDATIONS) if active_axes else ""
    upsell = get_upsell_hook()

    axes_display = [
        {"axis": ax, "label_ru": AXIS_LABELS_RU.get(ax, ax), "emoji": AXIS_EMOJI.get(ax, "")}
        for ax in AXES
    ]

    return {
        "version": MICROBIOME_ENGINE_VERSION,
        "active": bool(active_axes) or total_score > 0,
        "risk_scores": {
            "total_score": total_score,
            "level": level,
            "level_ru": level_ru,
        },
        "active_axes": active_axes,
        "axes_display": axes_display,
        "insights": insights,
        "recommendations": list(DEFAULT_RECOMMENDATIONS),
        "report_body": report_body,
        "upsell_hooks": [upsell],
        "entities": entities,
    }
