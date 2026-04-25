from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

FOLLOWUP_STATE_KEY = "medical_core_followup"


@dataclass
class PendingQuestion:
    question: str = ""
    slot: str = "generic"
    asked_turn_id: str = ""
    asked_count: int = 0
    gentle_reask_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FollowupState:
    current_bucket: str = ""
    phase: str = "collect"  # collect | ready | urgent
    turn_counter: int = 0
    answered_slots: dict[str, str] = field(default_factory=dict)
    answered_evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    asked_questions: list[dict[str, Any]] = field(default_factory=list)
    pending_question: PendingQuestion = field(default_factory=PendingQuestion)
    latest_question_source: str = ""
    stop_reason: str = ""
    final_ready: bool = False
    triage_level: str = ""
    triage_target: str = ""
    specialist: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["pending_question"] = self.pending_question.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "FollowupState":
        data = dict(payload or {})
        pending = data.get("pending_question") or {}
        return cls(
            current_bucket=str(data.get("current_bucket") or ""),
            phase=str(data.get("phase") or "collect"),
            turn_counter=int(data.get("turn_counter") or 0),
            answered_slots={str(k): str(v) for k, v in dict(data.get("answered_slots") or {}).items() if str(v).strip()},
            answered_evidence={str(k): dict(v or {}) for k, v in dict(data.get("answered_evidence") or {}).items()},
            asked_questions=[dict(x or {}) for x in list(data.get("asked_questions") or []) if isinstance(x, dict)],
            pending_question=PendingQuestion(
                question=str(pending.get("question") or ""),
                slot=str(pending.get("slot") or "generic"),
                asked_turn_id=str(pending.get("asked_turn_id") or ""),
                asked_count=int(pending.get("asked_count") or 0),
                gentle_reask_count=int(pending.get("gentle_reask_count") or 0),
            ),
            latest_question_source=str(data.get("latest_question_source") or ""),
            stop_reason=str(data.get("stop_reason") or ""),
            final_ready=bool(data.get("final_ready") or False),
            triage_level=str(data.get("triage_level") or ""),
            triage_target=str(data.get("triage_target") or ""),
            specialist=str(data.get("specialist") or ""),
        )


def read_followup_state(orchestrator_state: dict[str, Any] | None) -> FollowupState:
    state = dict(orchestrator_state or {})
    return FollowupState.from_dict(state.get(FOLLOWUP_STATE_KEY) or {})


def attach_followup_state(orchestrator_state: dict[str, Any] | None, followup_state: FollowupState | dict[str, Any]) -> dict[str, Any]:
    state = dict(orchestrator_state or {})
    if isinstance(followup_state, FollowupState):
        payload = followup_state.to_dict()
    else:
        payload = FollowupState.from_dict(followup_state).to_dict()
    state[FOLLOWUP_STATE_KEY] = payload
    return state


def prime_followup_state(
    orchestrator_state: dict[str, Any] | None,
    *,
    selector_payload: dict[str, Any] | None = None,
    triage_level: str | None = None,
    triage_target: str | None = None,
    specialist: str | None = None,
) -> FollowupState:
    current = read_followup_state(orchestrator_state)
    selector = dict(selector_payload or {})
    if selector:
        current.current_bucket = str(selector.get("entry_id") or selector.get("entry_name") or current.current_bucket)
        current.triage_level = str(selector.get("triage_level") or triage_level or current.triage_level)
        current.triage_target = str(selector.get("triage_target") or triage_target or current.triage_target)
        current.specialist = str(selector.get("specialist") or specialist or current.specialist)
    else:
        current.triage_level = str(triage_level or current.triage_level)
        current.triage_target = str(triage_target or current.triage_target)
        current.specialist = str(specialist or current.specialist)
    return current


def set_pending_question(
    followup_state: FollowupState,
    *,
    question: str,
    slot: str,
    source: str = "",
    turn_id: str = "",
) -> FollowupState:
    clean_q = str(question or "").strip()
    clean_slot = str(slot or "generic").strip() or "generic"
    existing = followup_state.pending_question
    asked_count = 1
    gentle_reask_count = 0
    if existing.question and existing.question == clean_q:
        asked_count = existing.asked_count + 1
        gentle_reask_count = existing.gentle_reask_count
    followup_state.pending_question = PendingQuestion(
        question=clean_q,
        slot=clean_slot,
        asked_turn_id=str(turn_id or ""),
        asked_count=asked_count,
        gentle_reask_count=gentle_reask_count,
    )
    followup_state.latest_question_source = str(source or followup_state.latest_question_source)
    followup_state.asked_questions.append(
        {
            "question": clean_q,
            "slot": clean_slot,
            "source": str(source or ""),
            "turn_id": str(turn_id or ""),
            "asked_count": asked_count,
        }
    )
    return followup_state


def clear_pending_question(followup_state: FollowupState) -> FollowupState:
    followup_state.pending_question = PendingQuestion()
    return followup_state


def register_answer(
    followup_state: FollowupState,
    *,
    slot: str,
    normalized_answer: str,
    raw_answer: str,
    confidence: float,
    evidence: dict[str, Any] | None = None,
) -> FollowupState:
    clean_slot = str(slot or "generic").strip() or "generic"
    clean_norm = str(normalized_answer or "").strip()
    if clean_norm:
        followup_state.answered_slots[clean_slot] = clean_norm
        followup_state.answered_evidence[clean_slot] = {
            "normalized_answer": clean_norm,
            "raw_answer": str(raw_answer or "").strip(),
            "confidence": float(confidence or 0.0),
            **dict(evidence or {}),
        }
    clear_pending_question(followup_state)
    return followup_state


def mark_reask(followup_state: FollowupState) -> FollowupState:
    followup_state.pending_question.gentle_reask_count += 1
    return followup_state


def mark_ready(followup_state: FollowupState, reason: str) -> FollowupState:
    followup_state.phase = "ready"
    followup_state.final_ready = True
    followup_state.stop_reason = str(reason or "enough_data")
    clear_pending_question(followup_state)
    return followup_state


def mark_urgent(followup_state: FollowupState, reason: str) -> FollowupState:
    followup_state.phase = "urgent"
    followup_state.final_ready = True
    followup_state.stop_reason = str(reason or "urgent")
    clear_pending_question(followup_state)
    return followup_state

