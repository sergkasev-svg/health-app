from __future__ import annotations

import time
from typing import Any


DEFAULT_VOICE_STATE = {
    "turn_id": 0,
    "mode": "push_to_talk",
    "awaiting_followup": False,
    "last_question": "",
    "last_question_source": "",
    "last_response": "",
    "last_user_message": "",
    "updated_at": 0.0,
}


def default_voice_state() -> dict[str, Any]:
    state = dict(DEFAULT_VOICE_STATE)
    state["updated_at"] = round(time.time(), 2)
    return state


def normalize_voice_state(raw: dict | None) -> dict[str, Any]:
    state = default_voice_state()
    if isinstance(raw, dict):
        state.update({k: v for k, v in raw.items() if k in state})
    state["turn_id"] = int(state.get("turn_id") or 0)
    state["awaiting_followup"] = bool(state.get("awaiting_followup"))
    state["last_question"] = str(state.get("last_question") or "").strip()
    state["last_question_source"] = str(state.get("last_question_source") or "").strip()
    state["last_response"] = str(state.get("last_response") or "").strip()
    state["last_user_message"] = str(state.get("last_user_message") or "").strip()
    state["mode"] = "push_to_talk"
    state["updated_at"] = round(time.time(), 2)
    return state


def extract_followup_question(result: dict[str, Any]) -> str:
    structured = result.get("structured") or {}
    questions = (
        structured.get("follow_up_questions")
        or structured.get("suggested_questions")
        or []
    )
    if isinstance(questions, list):
        for item in questions:
            text = str(item or "").strip()
            if text:
                return text
    nested = result.get("questions") or []
    if isinstance(nested, list):
        for item in nested:
            if isinstance(item, dict):
                text = str(item.get("question") or item.get("text") or "").strip()
            else:
                text = str(item or "").strip()
            if text:
                return text
    return ""


def build_voice_meta(result: dict[str, Any], previous_state: dict[str, Any]) -> dict[str, Any]:
    question = extract_followup_question(result)
    awaiting = bool(question) and not bool(result.get("conclusion"))
    red_flags = bool(result.get("red_flags_present"))
    severity = str(result.get("severity") or "YELLOW").upper()
    return {
        "turn_id": int(previous_state.get("turn_id") or 0) + 1,
        "mode": "push_to_talk",
        "awaiting_followup": awaiting,
        "last_question": question,
        "last_question_source": str(result.get("response_source") or "").strip(),
        "last_response": str(result.get("response") or "").strip(),
        "last_user_message": str(previous_state.get("last_user_message") or "").strip(),
        "red_flags_present": red_flags,
        "severity": severity,
        "barge_in_allowed": False,
        "auto_relisten_allowed": False,
        "should_confirm_critical": red_flags or severity == "RED",
        "updated_at": round(time.time(), 2),
    }
