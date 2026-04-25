# -*- coding: utf-8 -*-
"""
Case Storage Engine (V7): сохраняет диагностические кейсы для самообучения.
"""
from __future__ import annotations

import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2].parent
CASE_DB = _PROJECT_ROOT / "medical_learning" / "cases.json"


def save_case(symptoms: list[str], diagnosis: str, confirmed: str) -> None:
    case = {
        "symptoms": list(symptoms) if symptoms else [],
        "ai_diagnosis": diagnosis or "",
        "confirmed_diagnosis": confirmed or "",
    }
    if CASE_DB.exists():
        data = json.loads(CASE_DB.read_text(encoding="utf-8"))
    else:
        data = []
        CASE_DB.parent.mkdir(parents=True, exist_ok=True)
    data.append(case)
    CASE_DB.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
