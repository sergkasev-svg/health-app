"""
Bridge voice concierge payload with follow-up state machine metadata.

Add-only helper: enriches `voice_meta` with strict turn instructions while
keeping existing route/pipeline behavior unchanged.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


REASK_PATTERNS = {
    "duration": "Я уточню коротко: как давно это началось — часы, дни или недели?",
    "location": "Уточните, пожалуйста: где именно сейчас ощущается симптом?",
    "character": "Скажите, пожалуйста, какой характер симптома: ноющий, колющий, давящий или другой?",
    "severity": "Оцените выраженность по шкале от 0 до 10.",
    "temperature": "Была ли температура? Если была, какая максимальная?",
    "trigger": "С чем это было связано: еда, нагрузка, стресс, перегрев или другое?",
    "breath": "Есть ли сейчас одышка или ощущение нехватки воздуха?",
    "bleeding": "Есть ли кровотечение сейчас и откуда именно?",
    "stool": "Есть ли изменения стула: диарея, запор, кровь, слизь или черный цвет?",
    "urination": "Есть ли боль, жжение, частые позывы или кровь при мочеиспускании?",
    "vomiting": "Были ли рвота или сильная тошнота? Сколько раз и связаны ли с приемом пищи?",
    "pregnancy": "Возможна ли беременность или есть задержка цикла?",
    "neuro": "Есть ли онемение, слабость в руке или ноге, перекос лица, нарушение речи?",
}

VOICE_DEFAULTS = {
    "mode": "push_to_talk",
    "strict_one_question": True,
    "auto_send_after_utterance": False,
    "auto_relisten_allowed": False,
    "barge_in_allowed": False,
    "min_response_delay_sec": 1.35,
    "urgent_min_response_delay_sec": 0.55,
    "restart_listen_ms": 650,
    "silence_auto_send_ms": 2500,
}


@dataclass
class VoiceTurnInstruction:
    turn_status: str = "normal"  # normal | reask | urgent | final
    pending_question: Optional[str] = None
    pending_slot: Optional[str] = None
    should_listen_again: bool = False
    should_speak: bool = True
    should_wait_for_manual_send: bool = True
    min_response_delay_sec: float = 1.35
    hint: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _get_followup_state(orchestrator_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(orchestrator_state, dict):
        return {}
    return dict(orchestrator_state.get("medical_core_followup") or {})


def _get_pending(followup_state: Dict[str, Any]) -> Dict[str, Any]:
    pending = followup_state.get("pending_question") or {}
    return dict(pending) if isinstance(pending, dict) else {}


def _pending_question_text(pending: Dict[str, Any]) -> Optional[str]:
    # Compat: some variants use "question", some use "text".
    q = str(pending.get("question") or pending.get("text") or "").strip()
    return q or None


def build_voice_turn_instruction(
    *,
    orchestrator_state: Optional[Dict[str, Any]],
    voice_meta: Optional[Dict[str, Any]] = None,
    urgent: bool = False,
    followup_finished: bool = False,
    user_answer_matches_pending: Optional[bool] = None,
) -> Dict[str, Any]:
    followup_state = _get_followup_state(orchestrator_state)
    pending = _get_pending(followup_state)
    slot = str(pending.get("slot") or "").strip() or None

    instruction = VoiceTurnInstruction()
    instruction.pending_slot = slot
    instruction.pending_question = _pending_question_text(pending)

    if urgent:
        instruction.turn_status = "urgent"
        instruction.should_listen_again = False
        instruction.min_response_delay_sec = VOICE_DEFAULTS["urgent_min_response_delay_sec"]
        instruction.hint = "urgent_path"
    elif followup_finished or not instruction.pending_question:
        instruction.turn_status = "final"
        instruction.should_listen_again = False
        instruction.min_response_delay_sec = VOICE_DEFAULTS["min_response_delay_sec"]
        instruction.hint = "followup_complete"
    elif user_answer_matches_pending is False:
        instruction.turn_status = "reask"
        instruction.pending_question = REASK_PATTERNS.get(str(slot or ""), instruction.pending_question)
        instruction.should_listen_again = False
        instruction.min_response_delay_sec = VOICE_DEFAULTS["min_response_delay_sec"]
        instruction.hint = "gentle_reask"
    else:
        instruction.turn_status = "normal"
        instruction.should_listen_again = False
        instruction.min_response_delay_sec = VOICE_DEFAULTS["min_response_delay_sec"]
        instruction.hint = "wait_manual_send"

    result = {"voice_defaults": dict(VOICE_DEFAULTS), "voice_turn": instruction.as_dict()}
    if isinstance(voice_meta, dict):
        merged = dict(voice_meta)
        merged.update(result)
        return merged
    return result


def merge_voice_turn_into_payload(
    payload: Dict[str, Any],
    *,
    orchestrator_state: Optional[Dict[str, Any]],
    urgent: bool = False,
    followup_finished: bool = False,
    user_answer_matches_pending: Optional[bool] = None,
) -> Dict[str, Any]:
    out = dict(payload or {})
    voice_meta = dict(out.get("voice_meta") or {})
    out["voice_meta"] = build_voice_turn_instruction(
        orchestrator_state=orchestrator_state,
        voice_meta=voice_meta,
        urgent=urgent,
        followup_finished=followup_finished,
        user_answer_matches_pending=user_answer_matches_pending,
    )
    return out

