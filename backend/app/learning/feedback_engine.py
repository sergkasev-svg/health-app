# -*- coding: utf-8 -*-
"""
Feedback Engine (V7): сохраняет кейс и обновляет вероятности в графе.
"""
from __future__ import annotations

from app.learning.case_storage_engine import save_case
from app.learning.model_training_engine import retrain
from app.learning.probability_update_engine import update_probabilities


def process_feedback(symptoms: list[str], ai_diag: str, confirmed_diag: str) -> None:
    save_case(symptoms, ai_diag, confirmed_diag)
    update_probabilities(symptoms, confirmed_diag)


def retrain_after_n_cases(n: int = 100) -> dict[str, int] | None:
    """Если в БД кейсов кратно n, вызывает retrain и возвращает статистику; иначе None."""
    from app.learning.case_storage_engine import CASE_DB
    import json
    if not CASE_DB.exists():
        return None
    data = json.loads(CASE_DB.read_text(encoding="utf-8"))
    count = len(data)
    if count > 0 and count % n == 0:
        return retrain()
    return None
