from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


UNKNOWN_PATTERNS = [
    r"\bне знаю\b",
    r"\bзатрудняюсь\b",
    r"\bне помню\b",
    r"\bне уверен\b",
    r"\bне понял\b",
    r"\bповторите\b",
]

PARTIAL_HINTS = {
    "duration": [r"\bчас", r"\bдн", r"\bнед", r"\bмесяц", r"\bвчера\b", r"\bсегодня\b"],
    "location": [r"\bголов", r"\bживот", r"\bгруд", r"\bгорл", r"\bнос", r"\bухо", r"\bспин", r"\bрук", r"\bног"],
    "character": [r"\bноющ", r"\bколющ", r"\bдавящ", r"\bжгуч", r"\bпульсир", r"\bрезк", r"\bтянущ"],
    "severity": [r"\b[1-9]/10\b", r"\b10/10\b", r"\bсильн", r"\bумерен", r"\bслаб"],
    "temperature": [r"\bтемператур", r"\b37", r"\b38", r"\b39", r"\bжар", r"\bозноб"],
    "trigger": [r"\bпосле\b", r"\bиз-за\b", r"\bна фоне\b", r"\bстресс", r"\bнагрузк", r"\bеда"],
    "breath": [r"\bодышк", r"\bтяжело дышать\b", r"\bне хватает воздуха\b"],
    "bleeding": [r"\bкров", r"\bкровотеч"],
    "stool": [r"\bстул\b", r"\bдиаре", r"\bзапор", r"\bчерн", r"\bслиз"],
    "urination": [r"\bмочеиспуск", r"\bжжение\b", r"\bпозыв", r"\bмоч"],
    "vomiting": [r"\bрвот", r"\bтошнот"],
    "pregnancy": [r"\bберемен", r"\bзадержк", r"\bцикл\b"],
    "neuro": [r"\bонем", r"\bслабост", r"\bперекос", r"\bречь\b", r"\bголовокруж"],
}

CONTRADICTION_PATTERNS = [
    (r"\b(нет|не было)\b.*\bтемператур", r"\b3[89](?:[.,]\d)?\b"),
    (r"\b(нет|не было)\b.*\bкров", r"\bкров"),
    (r"\b(нет|не)\b.*\bодышк", r"\bодышк"),
]

NEW_COMPLAINT_HINTS = [
    r"\bи( еще| ещё)? у меня\b",
    r"\bкстати\b",
    r"\bнов(ый|ая|ое)\b",
    r"\bдруг(ой|ая|ое)\b",
]

ESCALATION_HINTS = [
    r"\bнеме(ет|ют|ла)\b",
    r"\bне хватает воздуха\b",
    r"\bпотеря сознания\b",
    r"\bсильная боль в груди\b",
    r"\bсудорог",
]


@dataclass
class AnswerQualityResult:
    status: str
    score: float
    reasons: List[str] = field(default_factory=list)
    extracted: Dict[str, Any] = field(default_factory=dict)
    should_reask: bool = False
    should_escalate: bool = False
    shifted_case: bool = False


def _has_any(text: str, patterns: List[str]) -> bool:
    return any(re.search(p, text, flags=re.I) for p in patterns)


def _extract_slot_answer(slot: Optional[str], text: str) -> Dict[str, Any]:
    if not slot:
        return {}
    pats = PARTIAL_HINTS.get(slot, [])
    hits = [p for p in pats if re.search(p, text, flags=re.I)]
    if not hits:
        return {}
    return {"slot": slot, "evidence_count": len(hits), "raw_text": text}


def _contradictory(text: str) -> bool:
    temp_deny = bool(re.search(r"\b(нет|не было)\b", text, flags=re.I) and re.search(r"\bтемператур", text, flags=re.I))
    temp_value = None
    m = re.search(r"\b(\d{2}(?:[.,]\d)?)\b", text)
    if m:
        try:
            temp_value = float(str(m.group(1)).replace(",", "."))
        except Exception:
            temp_value = None
    if temp_deny and temp_value is not None and temp_value >= 38.0:
        return True
    for a, b in CONTRADICTION_PATTERNS:
        if re.search(a, text, flags=re.I) and re.search(b, text, flags=re.I):
            return True
    return False


def evaluate_answer_quality(
    *,
    user_text: str,
    pending_question: Optional[Dict[str, Any]],
    followup_state: Optional[Dict[str, Any]],
    previous_user_text: Optional[str] = None,
) -> AnswerQualityResult:
    text = (user_text or "").strip().lower()
    slot = (pending_question or {}).get("slot")

    if not text:
        return AnswerQualityResult(status="empty", score=0.0, reasons=["empty_input"], should_reask=True)

    if _has_any(text, ESCALATION_HINTS):
        return AnswerQualityResult(
            status="escalation",
            score=0.95,
            reasons=["urgent_turn_in_text"],
            should_escalate=True,
        )

    if _has_any(text, UNKNOWN_PATTERNS):
        return AnswerQualityResult(
            status="unknown",
            score=0.12,
            reasons=["unknown_or_repair_request"],
            should_reask=True,
        )

    shifted_case = _has_any(text, NEW_COMPLAINT_HINTS)
    extracted = _extract_slot_answer(slot, text)
    matched_slot = bool(extracted)

    if _contradictory(text):
        return AnswerQualityResult(
            status="contradictory",
            score=0.35,
            reasons=["contradiction_detected"],
            extracted=extracted,
            should_reask=True,
            shifted_case=shifted_case,
        )

    if slot and matched_slot and shifted_case:
        return AnswerQualityResult(
            status="partial_with_new_complaint",
            score=0.62,
            reasons=["slot_answer_present", "new_complaint_hint"],
            extracted=extracted,
            shifted_case=True,
        )

    if slot and matched_slot:
        return AnswerQualityResult(
            status="on_target",
            score=0.88,
            reasons=["slot_answer_present"],
            extracted=extracted,
            shifted_case=shifted_case,
        )

    if slot and not matched_slot:
        if len(text.split()) >= 4:
            return AnswerQualityResult(
                status="partial_off_target",
                score=0.42,
                reasons=["meaningful_but_not_slot_specific"],
                should_reask=True,
                shifted_case=shifted_case,
            )
        return AnswerQualityResult(
            status="off_target",
            score=0.2,
            reasons=["does_not_answer_pending_slot"],
            should_reask=True,
            shifted_case=shifted_case,
        )

    return AnswerQualityResult(
        status="on_target",
        score=0.5,
        reasons=["no_pending_slot"],
        shifted_case=shifted_case,
    )


def merge_quality_into_followup_state(
    followup_state: Dict[str, Any],
    quality: AnswerQualityResult,
) -> Dict[str, Any]:
    state = dict(followup_state or {})
    state["last_answer_quality"] = {
        "status": quality.status,
        "score": quality.score,
        "reasons": quality.reasons,
        "shifted_case": quality.shifted_case,
        "should_reask": quality.should_reask,
        "should_escalate": quality.should_escalate,
    }
    if quality.extracted:
        answered_slots = dict(state.get("answered_slots") or {})
        answered_slots[str(quality.extracted.get("slot") or "generic")] = quality.extracted
        state["answered_slots"] = answered_slots
    if quality.shifted_case:
        state["case_shift_candidate"] = True
    return state

