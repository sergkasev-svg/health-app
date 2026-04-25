"""
Microbiome Engine v1 — боевой модуль анализа осей кишечник–организм.
Оси: gut_muscle, gut_brain, gut_immune, gut_skin.
Точки входа: symptoms, labs, lifestyle.
Выход: risk_scores, insights, recommendations, upsell_hooks.
"""
from __future__ import annotations

from app.services.microbiome_engine.engine import run_microbiome_engine
from app.services.microbiome_engine.config import (
    MICROBIOME_ENGINE_VERSION,
    AXES,
    ENTRY_POINTS,
)

__all__ = [
    "run_microbiome_engine",
    "MICROBIOME_ENGINE_VERSION",
    "AXES",
    "ENTRY_POINTS",
]

MICROBIOME_ENGINE_VERSION = "1.0"
AXES = ["gut_muscle", "gut_brain", "gut_immune", "gut_skin"]
ENTRY_POINTS = ["symptoms", "labs", "lifestyle"]
