"""
Генерация инсайтов по осям Microbiome Engine v1.
"""
from __future__ import annotations

from typing import Any

from app.services.microbiome_engine.config import ENTITIES, AXES

AXIS_INSIGHT_TEMPLATES = {
    "gut_muscle": (
        "Есть данные, что микробиом кишечника может влиять на мышечную силу и энергию "
        "через ось кишечник–мышцы. Это перспективное направление исследований, не замена базовым мерам."
    ),
    "gut_brain": (
        "Есть данные, что микробиом кишечника может влиять на настроение и стресс-ответ "
        "через ось кишечник–мозг."
    ),
    "gut_immune": (
        "Состояние микробиома связано с работой иммунитета. Разнообразие бактерий и клетчатка "
        "поддерживают барьерную функцию и противовоспалительные механизмы."
    ),
    "gut_skin": (
        "Исследования показывают связь между кишечником и состоянием кожи — ось кишечник–кожа. "
        "Коррекция питания и микробиома может быть дополнительным фактором."
    ),
}


def build_insight(axis: str, confidence: str = "emerging") -> dict[str, Any]:
    """Один инсайт по оси."""
    text = AXIS_INSIGHT_TEMPLATES.get(
        axis,
        "Микробиом кишечника может влиять на разные системы организма. Это область активных исследований.",
    )
    return {
        "type": "insight",
        "axis": axis,
        "text": text,
        "confidence": confidence,
    }


def get_entities_for_axes(active_axes: list[str]) -> list[dict[str, Any]]:
    """Сущности (микробы), релевантные активным осям."""
    out = []
    for ent in ENTITIES:
        if set(ent["axis"]) & set(active_axes):
            out.append(ent)
    return out


def generate_insights_for_axes(active_axes: list[str]) -> list[dict[str, Any]]:
    """Список инсайтов по активным осям."""
    return [build_insight(ax) for ax in active_axes if ax in AXES]
