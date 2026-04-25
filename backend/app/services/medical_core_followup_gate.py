from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from app.services.medical_core_followup_state import (
    FollowupState,
    mark_ready,
    mark_reask,
    mark_urgent,
    register_answer,
    set_pending_question,
)

CARE_LEVEL_WEIGHT = {
    "self_care": 0,
    "planned_consult": 1,
    "same_day": 2,
    "urgent": 3,
    "emergency": 4,
    "emergency_ambulance": 5,
}

UNSURE_PATTERNS = [
    r"\bне знаю\b",
    r"\bне помню\b",
    r"\bне уверен\b",
    r"\bзатрудняюсь\b",
    r"\bне понял\b",
]

SLOT_PATTERNS: dict[str, list[str]] = {
    "duration": [r"\bкак давно\b", r"\bсколько (времени|дней|часов)\b"],
    "location": [r"\bгде\b", r"\bв каком месте\b", r"\bлокализ"],
    "character": [r"\bкакая\b.*\bболь\b", r"\bхарактер\b", r"\bноющая\b", r"\bколющая\b", r"\bдавящая\b"],
    "severity": [r"\bнасколько\b", r"\b0.?10\b", r"\bсила боли\b"],
    "temperature": [r"\bтемператур", r"\bжар\b", r"\bозноб\b"],
    "trigger": [r"\bпосле чего\b", r"\bпровоцир", r"\bусилива", r"\bсвязано ли\b"],
    "breath": [r"\bодышк", r"\bтяжело дышать\b", r"\bне хватает воздуха\b"],
    "bleeding": [r"\bкров", r"\bкровотеч"],
    "stool": [r"\bстул\b", r"\bдиаре", r"\bзапор\b"],
    "urination": [r"\bмочеиспуск", r"\bмоч\b"],
    "vomiting": [r"\bрвот", r"\bтошнот"],
    "pregnancy": [r"\bберемен", r"\bзадержк", r"\bцикл\b"],
    "neuro": [r"\bонем", r"\bслабост", r"\bперекос", r"\bречь\b"],
}

LOCATION_KEYWORDS = [
    "голова",
    "грудь",
    "живот",
    "горло",
    "ухо",
    "нос",
    "спина",
    "поясница",
    "рука",
    "нога",
    "палец",
]
CHARACTER_KEYWORDS = ["ноющая", "колющая", "давящая", "жгучая", "пульсирующая", "резкая", "тянущая"]
TRIGGER_KEYWORDS = ["после еды", "после нагрузки", "после травмы", "после стресса", "ночью", "утром", "на жаре"]
YES_WORDS = {"да", "есть", "ага", "бывает", "присутствует", "положительно"}
NO_WORDS = {"нет", "не", "не было", "отрицательно", "не отмечаю"}


@dataclass
class AnswerAssessment:
    answered: bool
    slot: str
    normalized_answer: str = ""
    raw_answer: str = ""
    confidence: float = 0.0
    unsure: bool = False
    off_topic: bool = False
    evidence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FollowupDecision:
    action: str  # ask | reask | finalize | urgent
    question: str = ""
    ack: str = ""
    reason: str = ""
    slot: str = ""
    answered_slots: dict[str, str] | None = None
    followup_state: dict[str, Any] | None = None
    answer_assessment: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def infer_slot(question: str) -> str:
    q = str(question or "").lower()
    if not q:
        return "generic"
    for slot, patterns in SLOT_PATTERNS.items():
        if any(re.search(p, q, re.I) for p in patterns):
            return slot
    return "generic"


def _contains_any(text: str, keywords: list[str]) -> str:
    t = str(text or "").lower()
    for item in keywords:
        if item in t:
            return item
    return ""


def _extract_duration(text: str) -> str:
    t = str(text or "").lower()
    m = re.search(r"\b(\d+)\s*(час|часа|часов|день|дня|дней|недел|недели|месяц|месяца|месяцев)\b", t, re.I)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    for marker in ("сегодня", "вчера", "недавно", "давно", "несколько дней", "несколько часов"):
        if marker in t:
            return marker
    return ""


def _extract_scale(text: str) -> str:
    t = str(text or "")
    m = re.search(r"\b([0-9]|10)\s*(?:/|из\s*)\s*10\b", t, re.I)
    if m:
        return m.group(1) + "/10"
    m = re.search(r"\b([0-9]|10)\b", t)
    if m and any(k in t.lower() for k in ["балл", "боль", "из 10"]):
        return m.group(1) + "/10"
    return ""


def assess_answer(user_message: str, pending_question: str, slot_hint: str = "") -> AnswerAssessment:
    raw = str(user_message or "").strip()
    slot = str(slot_hint or infer_slot(pending_question) or "generic")
    if not raw:
        return AnswerAssessment(answered=False, slot=slot, raw_answer=raw, confidence=0.0, unsure=True)
    lower = raw.lower()
    if any(re.search(p, lower, re.I) for p in UNSURE_PATTERNS):
        return AnswerAssessment(answered=False, slot=slot, raw_answer=raw, confidence=0.2, unsure=True)

    normalized = ""
    confidence = 0.3
    evidence: dict[str, Any] = {"slot": slot}

    if slot == "duration":
        normalized = _extract_duration(raw)
        confidence = 0.9 if normalized else 0.2
    elif slot == "location":
        normalized = _contains_any(raw, LOCATION_KEYWORDS)
        confidence = 0.85 if normalized else 0.35
    elif slot == "character":
        normalized = _contains_any(raw, CHARACTER_KEYWORDS)
        confidence = 0.85 if normalized else 0.35
    elif slot == "severity":
        normalized = _extract_scale(raw)
        confidence = 0.9 if normalized else 0.3
    elif slot == "temperature":
        m = re.search(r"\b(3[5-9](?:[.,]\d)?|4[0-2](?:[.,]\d)?)\b", lower)
        if m:
            normalized = m.group(1).replace(",", ".")
            confidence = 0.95
        elif any(w in lower for w in YES_WORDS):
            normalized = "есть"
            confidence = 0.75
        elif any(w in lower for w in NO_WORDS):
            normalized = "нет"
            confidence = 0.75
    elif slot in {"breath", "bleeding", "vomiting", "pregnancy", "neuro", "stool", "urination"}:
        if any(w in lower for w in YES_WORDS):
            normalized = "да"
            confidence = 0.8
        elif any(w in lower for w in NO_WORDS):
            normalized = "нет"
            confidence = 0.8
        else:
            normalized = raw[:64]
            confidence = 0.55
    elif slot == "trigger":
        normalized = _contains_any(raw, TRIGGER_KEYWORDS)
        confidence = 0.8 if normalized else 0.4
    else:
        normalized = raw[:72]
        confidence = 0.55

    answered = bool(normalized and confidence >= 0.5)
    off_topic = False
    if not answered:
        meaningful_words = [w for w in re.split(r"\W+", lower) if len(w) > 3]
        q_words = {w for w in re.split(r"\W+", str(pending_question or "").lower()) if len(w) > 3}
        overlap = [w for w in meaningful_words if w in q_words]
        off_topic = len(overlap) == 0 and len(meaningful_words) >= 3

    return AnswerAssessment(
        answered=answered,
        slot=slot,
        normalized_answer=normalized,
        raw_answer=raw,
        confidence=confidence,
        unsure=False,
        off_topic=off_topic,
        evidence=evidence,
    )


def _gentle_reask(question: str, slot: str) -> str:
    if slot == "duration":
        return "Я уточню коротко: как давно это началось — часы, дни или недели?"
    if slot == "location":
        return "Подскажите, пожалуйста, где именно это ощущается?"
    if slot == "character":
        return "Опишите, пожалуйста, характер симптома: ноющий, колющий, давящий или другой?"
    if slot == "severity":
        return "Оцените, пожалуйста, выраженность по шкале от 0 до 10."
    if slot == "temperature":
        return "Была ли температура и какая максимальная?"
    if slot == "trigger":
        return "С чем это обычно связано: после еды, нагрузки, стресса или без связи?"
    q = str(question or "").strip().rstrip("?")
    return f"Уточню коротко: {q}?"


def _enough_data(state: FollowupState, triage_level: str = "") -> tuple[bool, str]:
    if state.final_ready:
        return True, state.stop_reason or "already_ready"
    effective_triage = str(triage_level or state.triage_level).strip()
    if CARE_LEVEL_WEIGHT.get(effective_triage, 0) >= CARE_LEVEL_WEIGHT["same_day"] and len(state.answered_slots) >= 1:
        return True, "elevated_care_with_minimum_context"
    answered = set(state.answered_slots.keys())
    must_have_sets = [{"duration", "location"}, {"duration", "character"}, {"location", "character"}]
    if any(req.issubset(answered) for req in must_have_sets):
        return True, "enough_core_context"
    if len(answered) >= 3:
        return True, "three_answered_slots"
    return False, ""


def decide_followup_turn(
    *,
    user_message: str,
    followup_state: FollowupState,
    candidate_questions: list[str] | None = None,
    turn_id: str = "",
    question_source: str = "medical_core",
    selector_payload: dict[str, Any] | None = None,
    red_flags_present: bool = False,
    severity: str = "YELLOW",
) -> FollowupDecision:
    state = followup_state
    state.turn_counter += 1
    selector_payload = dict(selector_payload or {})
    if selector_payload:
        state.triage_level = str(selector_payload.get("triage_level") or state.triage_level)
        state.triage_target = str(selector_payload.get("triage_target") or state.triage_target)
        state.specialist = str(selector_payload.get("specialist") or state.specialist)

    if red_flags_present or str(severity).upper() == "RED":
        mark_urgent(state, "red_flags_present")
        return FollowupDecision(
            action="urgent",
            reason="red_flags_present",
            answered_slots=dict(state.answered_slots),
            followup_state=state.to_dict(),
        )

    pending = state.pending_question
    if pending.question:
        assessment = assess_answer(user_message=user_message, pending_question=pending.question, slot_hint=pending.slot)
        if assessment.answered:
            register_answer(
                state,
                slot=assessment.slot,
                normalized_answer=assessment.normalized_answer,
                raw_answer=assessment.raw_answer,
                confidence=assessment.confidence,
                evidence=assessment.evidence,
            )
            enough, reason = _enough_data(state, triage_level=state.triage_level)
            if enough:
                mark_ready(state, reason)
                return FollowupDecision(
                    action="finalize",
                    reason=reason,
                    slot=assessment.slot,
                    answered_slots=dict(state.answered_slots),
                    followup_state=state.to_dict(),
                    answer_assessment=assessment.to_dict(),
                )
        else:
            if pending.gentle_reask_count >= 1 or pending.asked_count >= 2:
                mark_ready(state, "reask_limit_reached")
                return FollowupDecision(
                    action="finalize",
                    reason="reask_limit_reached",
                    slot=pending.slot,
                    answered_slots=dict(state.answered_slots),
                    followup_state=state.to_dict(),
                    answer_assessment=assessment.to_dict(),
                )
            mark_reask(state)
            reask_question = _gentle_reask(pending.question, pending.slot)
            set_pending_question(state, question=reask_question, slot=pending.slot, source=f"{question_source}_reask", turn_id=turn_id)
            return FollowupDecision(
                action="reask",
                question=reask_question,
                reason="pending_question_not_answered",
                slot=pending.slot,
                answered_slots=dict(state.answered_slots),
                followup_state=state.to_dict(),
                answer_assessment=assessment.to_dict(),
            )

    enough, reason = _enough_data(state, triage_level=state.triage_level)
    if enough:
        mark_ready(state, reason)
        return FollowupDecision(
            action="finalize",
            reason=reason,
            answered_slots=dict(state.answered_slots),
            followup_state=state.to_dict(),
        )

    questions = [str(q).strip() for q in (candidate_questions or []) if str(q).strip()]
    if selector_payload.get("best_question"):
        best_q = str(selector_payload.get("best_question") or "").strip()
        if best_q and best_q not in questions:
            questions.insert(0, best_q)
    next_question = questions[0] if questions else ""
    if not next_question:
        mark_ready(state, "no_more_questions")
        return FollowupDecision(
            action="finalize",
            reason="no_more_questions",
            answered_slots=dict(state.answered_slots),
            followup_state=state.to_dict(),
        )

    slot = infer_slot(next_question)
    set_pending_question(state, question=next_question, slot=slot, source=question_source, turn_id=turn_id)
    return FollowupDecision(
        action="ask",
        question=next_question,
        reason="next_best_question",
        slot=slot,
        answered_slots=dict(state.answered_slots),
        followup_state=state.to_dict(),
    )

