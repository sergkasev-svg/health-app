# -*- coding: utf-8 -*-
"""
Clinical guidelines: сопоставление симптомов и анализов с правилами (evidence-based).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GUIDELINES: dict[str, Any] = {}
_LOADED = False


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2].parent


def load_guidelines() -> None:
    global GUIDELINES, _LOADED
    if _LOADED:
        return
    root = _project_root()
    path = root / "medical_knowledge" / "clinical_guidelines" / "guidelines.json"
    if path.exists():
        try:
            GUIDELINES = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            GUIDELINES = {}
    else:
        GUIDELINES = {}
    _LOADED = True


def evaluate_guidelines(
    symptoms: list[str],
    labs: dict[str, Any] | list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Возвращает правила, для которых выполнены все required symptoms."""
    load_guidelines()
    rules = GUIDELINES.get("rules", [])
    if not rules:
        return []
    symptom_set = set((s or "").strip().lower() for s in symptoms if s)
    matches: list[dict[str, Any]] = []
    for guideline in rules:
        required = guideline.get("symptoms", [])
        if not required:
            continue
        if all((r or "").strip().lower() in symptom_set for r in required):
            matches.append(guideline)
    return matches
