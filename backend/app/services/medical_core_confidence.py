from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


BASE_SLOT_WEIGHTS = {
    "duration": 0.10,
    "location": 0.16,
    "character": 0.12,
    "severity": 0.14,
    "temperature": 0.12,
    "trigger": 0.08,
    "breath": 0.18,
    "bleeding": 0.20,
    "stool": 0.08,
    "urination": 0.08,
    "vomiting": 0.08,
    "pregnancy": 0.12,
    "neuro": 0.22,
}

COMPLAINT_REQUIRED_SLOTS = {
    "chest_pain": ["duration", "character", "severity", "breath", "trigger"],
    "abdominal_pain": ["duration", "location", "character", "severity", "vomiting"],
    "headache": ["duration", "severity", "neuro", "temperature"],
    "shortness_of_breath": ["duration", "breath", "severity", "temperature", "trigger"],
    "urinary_symptoms": ["duration", "urination", "temperature", "bleeding"],
    "nosebleed": ["duration", "bleeding", "severity", "trigger", "temperature"],
    "anorectal_bleeding": ["duration", "bleeding", "stool", "severity", "trigger"],
    "wound_cut": ["duration", "bleeding", "location", "severity", "trigger"],
    "allergy_reaction": ["duration", "trigger", "breath", "severity", "temperature"],
    "food_trigger": ["duration", "trigger", "vomiting", "stool", "severity"],
    "hypertension": ["duration", "severity", "trigger", "neuro", "breath"],
    "fever_infection": ["duration", "temperature", "severity", "trigger", "breath"],
    "trauma_limb": ["duration", "location", "severity", "character", "neuro"],
}

COMPLAINT_STOP_THRESHOLDS = {
    "chest_pain": 0.72,
    "abdominal_pain": 0.70,
    "headache": 0.70,
    "shortness_of_breath": 0.74,
    "urinary_symptoms": 0.66,
    "nosebleed": 0.66,
    "anorectal_bleeding": 0.68,
    "wound_cut": 0.64,
    "allergy_reaction": 0.70,
    "food_trigger": 0.66,
    "hypertension": 0.70,
    "fever_infection": 0.64,
    "trauma_limb": 0.66,
    "_default": 0.68,
}

DOMAIN_REQUIRED_SLOTS = {
    "cardiology": ["duration", "character", "severity", "trigger", "breath"],
    "respiratory": ["duration", "breath", "temperature", "severity", "trigger"],
    "gi": ["duration", "location", "character", "severity", "vomiting"],
    "urology": ["duration", "urination", "temperature", "bleeding"],
    "neurology": ["duration", "severity", "neuro", "temperature"],
    "gynecology": ["duration", "severity", "pregnancy", "bleeding", "temperature"],
    "infectious": ["duration", "temperature", "severity", "trigger"],
    "ent": ["duration", "temperature", "severity", "bleeding"],
    "skin": ["duration", "location", "character", "severity"],
}

DOMAIN_STOP_THRESHOLDS = {
    "cardiology": 0.70,
    "respiratory": 0.70,
    "gi": 0.68,
    "urology": 0.66,
    "neurology": 0.70,
    "gynecology": 0.68,
    "infectious": 0.65,
    "ent": 0.66,
    "skin": 0.64,
}

_DOMAIN_HINTS = {
    "cardiology": ["cardio", "cardi", "сердц", "карди", "давлен", "груд"],
    "respiratory": ["resp", "дых", "одыш", "каш", "бронх", "легк"],
    "gi": ["gi", "gastro", "жкт", "живот", "киш", "желуд"],
    "urology": ["uro", "моч", "почк", "урин", "цистит"],
    "neurology": ["neuro", "невро", "голов", "мигр", "онем"],
    "gynecology": ["gyn", "гин", "жен", "беремен", "цикл"],
    "infectious": ["infect", "инфекц", "лихорад", "температ"],
    "ent": ["лор", "нос", "горл", "ухо", "sinus"],
    "skin": ["skin", "кожа", "сып", "дермат"],
}

_COMPLAINT_KEYWORDS = {
    "chest_pain": ["chest", "груд", "сердц", "стесн"],
    "abdominal_pain": ["abdomen", "abdominal", "живот", "желуд", "киш", "жкт"],
    "headache": ["headache", "голов", "мигр"],
    "shortness_of_breath": ["breath", "dyspnea", "одыш", "не хватает воздуха", "тяжело дышать"],
    "urinary_symptoms": ["urinary", "urination", "моч", "цистит", "почк"],
    "nosebleed": ["nosebleed", "эпистаксис", "кровь из носа", "носовое кровотечение"],
    "anorectal_bleeding": ["гемор", "кровь из заднего прохода", "аналь", "ректал", "кровь в стуле"],
    "wound_cut": ["порез", "рана", "кровь течет", "cut", "wound"],
    "allergy_reaction": ["аллерг", "сыпь", "отек", "анафилак", "allergy"],
    "food_trigger": ["после еды", "после творога", "после молока", "пищ", "food trigger"],
    "hypertension": ["давление", "гиперт", "пульс", "тахик", "лицо горит"],
    "fever_infection": ["температур", "озноб", "лихорад", "инфекц", "жар"],
    "trauma_limb": ["травм", "ушиб", "перелом", "вывих", "онемение руки", "онемение ноги"],
}

_CONFIDENCE_OVERRIDES_PATH = Path(__file__).resolve().parents[3] / "medical_knowledge" / "medical_core" / "confidence_profiles_overrides.json"


@dataclass
class ConfidenceDecision:
    confidence: float
    answered_slots: List[str] = field(default_factory=list)
    missing_slots: List[str] = field(default_factory=list)
    should_stop: bool = False
    should_ask_one_more: bool = True
    next_best_slot: Optional[str] = None
    reasons: List[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def _load_overrides() -> dict[str, Any]:
    if not _CONFIDENCE_OVERRIDES_PATH.exists():
        return {}
    try:
        data = json.loads(_CONFIDENCE_OVERRIDES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _care_level_adjustment(triage_level: str) -> float:
    tl = str(triage_level or "").strip().lower()
    if tl in {"same_day"}:
        return -0.06
    if tl in {"planned_consult"}:
        return -0.02
    if tl in {"self_care"}:
        return +0.03
    return 0.0


def _infer_domain(state: Dict[str, Any], candidates: list[str]) -> str:
    direct = str(state.get("domain") or "").strip().lower()
    if direct in DOMAIN_REQUIRED_SLOTS:
        return direct
    for raw in candidates:
        for domain, hints in _DOMAIN_HINTS.items():
            if any(h in raw for h in hints):
                return domain
    return ""


def _resolve_profile(state: Dict[str, Any], candidates: list[str], triage_level: str) -> tuple[str, list[str], float]:
    overrides = _load_overrides()
    complaint_overrides = overrides.get("complaint_overrides") if isinstance(overrides, dict) else {}
    domain_overrides = overrides.get("domain_overrides") if isinstance(overrides, dict) else {}
    default_threshold = float(overrides.get("default_threshold") or COMPLAINT_STOP_THRESHOLDS["_default"]) if isinstance(overrides, dict) else COMPLAINT_STOP_THRESHOLDS["_default"]

    complaint_key = "_default"
    for raw in candidates:
        if raw in COMPLAINT_REQUIRED_SLOTS:
            complaint_key = raw
            break
        for key, kw_list in _COMPLAINT_KEYWORDS.items():
            if any(kw in raw for kw in kw_list):
                complaint_key = key
                break
        if complaint_key != "_default":
            break

    if complaint_key != "_default":
        required = list(COMPLAINT_REQUIRED_SLOTS.get(complaint_key, []))
        threshold = float(COMPLAINT_STOP_THRESHOLDS.get(complaint_key, default_threshold))
        if isinstance(complaint_overrides, dict) and isinstance(complaint_overrides.get(complaint_key), dict):
            row = complaint_overrides.get(complaint_key) or {}
            if isinstance(row.get("required_slots"), list):
                required = [str(x).strip() for x in row.get("required_slots") if str(x).strip()]
            if row.get("threshold") is not None:
                try:
                    threshold = float(row.get("threshold"))
                except Exception:
                    pass
        threshold = max(0.5, min(0.9, threshold + _care_level_adjustment(triage_level)))
        return complaint_key, required, threshold

    domain = _infer_domain(state, candidates)
    if domain:
        required = list(DOMAIN_REQUIRED_SLOTS.get(domain, []))
        threshold = float(DOMAIN_STOP_THRESHOLDS.get(domain, default_threshold))
        if isinstance(domain_overrides, dict) and isinstance(domain_overrides.get(domain), dict):
            row = domain_overrides.get(domain) or {}
            if isinstance(row.get("required_slots"), list):
                required = [str(x).strip() for x in row.get("required_slots") if str(x).strip()]
            if row.get("threshold") is not None:
                try:
                    threshold = float(row.get("threshold"))
                except Exception:
                    pass
        threshold = max(0.5, min(0.9, threshold + _care_level_adjustment(triage_level)))
        return domain, required, threshold

    fallback_required = ["duration", "severity", "location", "trigger"]
    fallback_threshold = max(0.5, min(0.9, default_threshold + _care_level_adjustment(triage_level)))
    return "_default", fallback_required, fallback_threshold


def _normalize_complaint_key(state: Dict[str, Any]) -> tuple[str, list[str]]:
    candidates: list[str] = []
    for key in ("selector_complaint", "complaint_key", "complaint_id", "current_branch", "entry_name", "entry_id"):
        val = state.get(key)
        if isinstance(val, str) and val.strip():
            candidates.append(val.strip().lower())
    if isinstance(state.get("category"), str) and state.get("category"):
        candidates.append(str(state.get("category") or "").strip().lower())
    if isinstance(state.get("domain"), str) and state.get("domain"):
        candidates.append(str(state.get("domain") or "").strip().lower())
    return (candidates[0] if candidates else "_default"), candidates


def _collect_answered_slots(followup_state: Dict[str, Any]) -> Dict[str, Any]:
    return dict((followup_state or {}).get("answered_slots") or {})


def _score_answered_slots(complaint_key: str, answered_slots: Dict[str, Any]) -> float:
    required = COMPLAINT_REQUIRED_SLOTS.get(complaint_key, [])
    if not required:
        required = list(BASE_SLOT_WEIGHTS.keys())[:4]

    covered_weight = 0.0
    required_weight = 0.0
    for slot in required:
        required_weight += BASE_SLOT_WEIGHTS.get(slot, 0.08)
        if slot in answered_slots:
            covered_weight += BASE_SLOT_WEIGHTS.get(slot, 0.08)

    coverage_ratio = (covered_weight / required_weight) if required_weight > 0 else 0.0
    score = min(coverage_ratio * 0.82, 0.82)

    extra_count = len([s for s in answered_slots.keys() if s not in required])
    score += min(extra_count * 0.04, 0.16)
    return min(score, 0.98)


def _pick_next_best_slot(complaint_key: str, answered_slots: Dict[str, Any], triage_level: Optional[str]) -> Optional[str]:
    required = COMPLAINT_REQUIRED_SLOTS.get(complaint_key, [])
    if not required:
        required = ["duration", "severity", "location", "trigger"]
    candidates = [s for s in required if s not in answered_slots]
    if not candidates:
        return None

    if str(triage_level or "").strip().lower() in {"urgent", "emergency"}:
        for slot in ("breath", "bleeding", "neuro", "severity", "temperature"):
            if slot in candidates:
                return slot

    weighted = sorted(candidates, key=lambda s: BASE_SLOT_WEIGHTS.get(s, 0.05), reverse=True)
    return weighted[0] if weighted else candidates[0]


def decide_confidence_stop(
    *,
    orchestrator_state: Optional[Dict[str, Any]],
    followup_state: Optional[Dict[str, Any]],
) -> ConfidenceDecision:
    state = dict(orchestrator_state or {})
    fstate = dict(followup_state or {})
    primary_key, candidates = _normalize_complaint_key(state)
    triage_level = str(state.get("triage_level") or state.get("triage_label") or "").strip().lower()
    profile_key, required, threshold = _resolve_profile(state, candidates + [primary_key], triage_level)
    answered = _collect_answered_slots(fstate)

    confidence = _score_answered_slots(profile_key if profile_key in COMPLAINT_REQUIRED_SLOTS else "_default", answered)
    if required:
        # Re-score against resolved profile template for better domain coverage.
        fake_profile_key = profile_key if profile_key in COMPLAINT_REQUIRED_SLOTS else "_default"
        if fake_profile_key == "_default":
            covered = {k: v for k, v in answered.items() if k in required}
            confidence = _score_answered_slots("_default", covered)
            if covered:
                confidence = max(confidence, min(0.92, len(covered) / max(1, len(required)) * 0.82))
    missing = [slot for slot in required if slot not in answered]

    should_stop = False
    reasons: List[str] = [f"profile:{profile_key}", f"threshold:{threshold:.2f}"]

    if bool(state.get("urgent")) or triage_level in {"urgent", "emergency"}:
        reasons.append("urgent_context_present")
        return ConfidenceDecision(
            confidence=max(confidence, 0.75),
            answered_slots=list(answered.keys()),
            missing_slots=missing,
            should_stop=True,
            should_ask_one_more=False,
            next_best_slot=None,
            reasons=reasons,
        )

    if confidence >= threshold and len(answered) >= max(2, min(4, len(required) or 4)):
        should_stop = True
        reasons.append("confidence_threshold_reached")

    if required and (not missing) and confidence >= (threshold - 0.04):
        should_stop = True
        reasons.append("required_slots_covered")

    next_best_slot = None if should_stop else _pick_next_best_slot(profile_key if profile_key in COMPLAINT_REQUIRED_SLOTS else "_default", answered, triage_level)
    if not should_stop and not next_best_slot and missing:
        next_best_slot = missing[0]
    if next_best_slot:
        reasons.append(f"need_more_data:{next_best_slot}")

    return ConfidenceDecision(
        confidence=confidence,
        answered_slots=list(answered.keys()),
        missing_slots=missing,
        should_stop=should_stop,
        should_ask_one_more=not should_stop,
        next_best_slot=next_best_slot,
        reasons=reasons,
    )


def merge_confidence_into_state(
    *,
    orchestrator_state: Dict[str, Any],
    followup_state: Dict[str, Any],
    decision: ConfidenceDecision,
) -> Dict[str, Any]:
    state = dict(orchestrator_state or {})
    state["confidence_gate"] = {
        "confidence": decision.confidence,
        "answered_slots": decision.answered_slots,
        "missing_slots": decision.missing_slots,
        "should_stop": decision.should_stop,
        "should_ask_one_more": decision.should_ask_one_more,
        "next_best_slot": decision.next_best_slot,
        "reasons": decision.reasons,
    }
    state["followup_ready_for_summary"] = bool(decision.should_stop)

    if decision.next_best_slot:
        fstate = dict(followup_state or {})
        pending = dict(fstate.get("pending_question") or {})
        if not pending.get("slot"):
            pending["slot"] = decision.next_best_slot
            fstate["pending_question"] = pending
        state["medical_core_followup"] = fstate

    return state

