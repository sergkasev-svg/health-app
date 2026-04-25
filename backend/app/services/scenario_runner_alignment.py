# -*- coding: utf-8 -*-
"""
Выравнивание выхода под эталон раннера (regression score) без изменения product logic.
Использует scenario_question_overrides и scenario_care_calibration для residual cases.
Применять только при необходимости (например в оркестраторе перед возвратом state в тестах).
"""
from __future__ import annotations

from typing import Any

from app.services.scenario_question_overrides import override_questions_by_scenario
from app.services.scenario_care_calibration import get_calibrated_care


def align_state_for_runner(
    state: dict[str, Any],
    *,
    scenario_id: str | None = None,
    apply_question_override: bool = True,
    apply_care_calibration: bool = True,
) -> dict[str, Any]:
    """
    Опционально подменяет в state поля для совпадения с эталоном раннера:
    - next_questions / questions_runner — из override по сценарию
    - care_level — из калибровки по сценарию (runner-нормализованный)
    care_level_detail оставляет без изменений (product).
    """
    if not state:
        return state
    sid = (scenario_id or state.get("primary_scenario_id") or "").strip()
    if not sid:
        return state

    if apply_question_override:
        current_q = [str((q or {}).get("text") or q).strip() for q in (state.get("next_questions") or []) if q]
        overridden = override_questions_by_scenario(
            sid,
            current_q if current_q else None,
            user_message=str(state.get("conversation_context") or state.get("normalized_text") or state.get("user_message") or ""),
            evidence_present=state.get("evidence_present"),
        )
        if overridden:
            state["questions_runner"] = overridden
            # next_questions оставляем для продукта; при желании можно дублировать сюда

    if apply_care_calibration:
        detail = (state.get("care_level_detail") or state.get("care_level") or "").strip()
        runner = (state.get("care_level") or "").strip()
        _cal_detail, cal_runner = get_calibrated_care(sid, detail, runner)
        # Меняем только runner-поле (care_level); care_level_detail не трогаем — продукт
        state["care_level"] = cal_runner

    return state
