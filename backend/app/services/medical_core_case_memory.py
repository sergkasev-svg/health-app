from __future__ import annotations

from typing import Any

VOICE_OR_CONSULT_KEY = "medical_core_selector"


def attach_selector_state(orchestrator_state: dict[str, Any] | None, selector_payload: dict[str, Any]) -> dict[str, Any]:
    state = dict(orchestrator_state or {})
    block = dict(state.get(VOICE_OR_CONSULT_KEY) or {})
    block.update(selector_payload or {})
    state[VOICE_OR_CONSULT_KEY] = block
    return state


def read_selector_state(orchestrator_state: dict[str, Any] | None) -> dict[str, Any]:
    state = dict(orchestrator_state or {})
    return dict(state.get(VOICE_OR_CONSULT_KEY) or {})


def selector_followup_question(orchestrator_state: dict[str, Any] | None) -> str:
    block = read_selector_state(orchestrator_state)
    return str(block.get("best_question") or "").strip()

