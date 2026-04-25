"""Stateful consultation orchestrator v1."""
from __future__ import annotations

import re
from typing import Any, Optional

from app.services.consultation_contracts import ConsultationStateSnapshot
from app.services import case_state_manager
from app.services import care_level_engine
from app.services.care_level_normalizer import normalize_care_level
from app.services.care_level_engine import normalize_runner_care_level
from app.services import contradiction_checker
from app.services import diagnostic_ranking_engine
from app.services import input_normalizer
from app.services import question_selector
from app.services import red_flag_engine
from app.services import recommendation_policy
from app.services import response_composer
from app.services import response_safety_filter
from app.services import scenario_router
from app.services.scenario_branch_override import apply_scenario_branch_override
from app.services.scenario_care_overrides import override_care_level_by_scenario
from app.services.scenario_care_calibration import get_calibrated_care
from app.services.scenario_question_overrides import override_questions_by_scenario
from app.services import routing_control
from app.services import user_store as user_store_service
from app.services.medical_relevance_filter import MedicalRelevanceFilter
try:
    from app.services.unified_master_triage_engine import UnifiedMasterTriageEngine
except Exception:
    UnifiedMasterTriageEngine = None

try:
    from app.branches.zaz_food_branch_integration import (
        FoodBranchInput,
        ZaZFoodBranchIntegration,
    )
except Exception:
    ZaZFoodBranchIntegration = None
    FoodBranchInput = None


def _conversation_user_blob(chat_history: list[dict[str, Any]] | None, latest_user: str) -> str:
    """Склеивает последние реплики пользователя для фильтра «уже сказано» (не только последнее сообщение)."""
    parts: list[str] = []
    for m in (chat_history or [])[-16:]:
        if str((m or {}).get("role") or "").strip().lower() != "user":
            continue
        c = str((m or {}).get("content") or "").strip()
        if c:
            parts.append(c)
    tail = (latest_user or "").strip()
    if tail and (not parts or parts[-1] != tail):
        parts.append(tail)
    merged = " ".join(parts)
    return re.sub(r"\s+", " ", merged).strip()[:12000]

try:
    from app.services import clinical_extractor
except Exception:
    clinical_extractor = None

# Консьерж: не более стольких ответов ассистента с уточнениями подряд, затем — гипотеза и план.
MAX_CLARIFICATION_ROUNDS = 3
# Сколько вопросов показывать пользователю за один ответ (по одному, ждём ответ, затем следующий).
CONCIERGE_QUESTIONS_PER_REPLY = 1

_medical_relevance_filter = MedicalRelevanceFilter()
_food_branch = ZaZFoodBranchIntegration() if ZaZFoodBranchIntegration else None
_unified_master_triage = UnifiedMasterTriageEngine() if UnifiedMasterTriageEngine else None


def count_assistant_clarification_rounds(chat_history: list[dict[str, Any]] | None) -> int:
    """
    Число предыдущих ответов ассистента, где уже запрашивались уточнения (не приветствие).
    Используется, чтобы после лимита выдать итог, а не зациклить вопросы.
    """
    n = 0
    for item in chat_history or []:
        if (item or {}).get("role") != "assistant":
            continue
        content = str((item or {}).get("content") or "").strip()
        if not content:
            continue
        low = content.lower()
        # короткие приветствия без развёрнутого уточнения
        if len(content) < 70 and content.count("?") <= 1:
            if any(
                g in low
                for g in (
                    "здравствуйте",
                    "консультант",
                    "михаил",
                    "чем могу",
                    "чем я могу",
                    "с возвращением",
                    "рады видеть",
                )
            ):
                continue
        if "?" in content:
            n += 1
            continue
        if "уточн" in low or "что уточнить" in low or "наводящ" in low:
            n += 1
    return n


def _safe_user_text(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        for key in ("message", "text", "user_message", "query", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return str(payload).strip()


def _normalize_user_text_for_triage(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    low = raw.lower()
    # Remove common conversational wrappers that add routing noise.
    for prefix in (
        "привет",
        "здравствуйте",
        "добрый день",
        "подскажи пожалуйста",
        "подскажите пожалуйста",
        "поставь мне пожалуйста диагноз",
        "поставь диагноз",
        "у меня вот какая проблема",
        "у меня следующие симптомы",
    ):
        if low.startswith(prefix):
            raw = raw[len(prefix):].strip(" ,.-:")
            low = raw.lower()
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw or str(text or "").strip()


def _try_food_branch(
    *,
    user_text: str,
    previous_case_state: Optional[dict[str, Any]],
) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    if not _food_branch or not FoodBranchInput:
        return (None, previous_case_state)

    case_state = dict(previous_case_state or {})
    branch_memory = case_state.get("food_branch_memory")

    try:
        branch_input = FoodBranchInput(
            user_text=user_text,
            recurrent=bool(case_state.get("food_recurrent", False)),
            debug=False,
            ask_followups=True,
            doctor_safe=True,
            memory_state=branch_memory,
            food_journal_entries=list(case_state.get("food_journal_entries", []) or []),
            extra_context={"source": "stateful_triage"},
        )
        result = _food_branch.handle(branch_input)
    except Exception:
        return (None, case_state)

    if not getattr(result, "matched", False):
        return (None, case_state)

    case_state["food_branch_memory"] = result.memory_state
    case_state["food_branch_payload"] = {
        "branch": result.branch_name,
        "relevance_score": result.relevance_score,
        "care_level": result.care_level,
        "doctor_payload": result.doctor_safe_json,
        "machine_payload": result.machine_payload,
        "errors": result.errors,
    }
    case_state["primary_scenario_id"] = "food_postmeal_branch"
    case_state["last_clinical_update_reason"] = "specialized_branch:food_postmeal_branch"
    case_state["conversation_stage"] = "specialized_food"

    return (result.patient_safe_text or "", case_state)


def _render_unified_master_response(payload: dict[str, Any]) -> str:
    causes = list(payload.get("ranked_causes") or [])
    red_flags = list(payload.get("red_flags_detected") or [])
    recurrent = bool(payload.get("recurrent"))
    recurrent_tests = list(payload.get("recurrent_tests") or [])
    single_episode_message = str(payload.get("single_episode_message") or "").strip()

    lines: list[str] = []
    lines.append("Что вероятнее всего:")
    if causes:
        top = causes[0]
        lines.append(f"- {str(top.get('title') or top.get('id') or '').strip()}")
        for row in causes[1:3]:
            title = str(row.get("title") or row.get("id") or "").strip()
            if title:
                lines.append(f"- Также возможно: {title}")
    else:
        lines.append("- Нужны уточнения по симптомам и связи с едой.")

    if red_flags:
        lines.append("Когда срочно обращаться:")
        lines.extend(f"- {str(x).strip()}" for x in red_flags[:5] if str(x).strip())

    lines.append("Нужны ли анализы, если это повторяется:")
    if recurrent and recurrent_tests:
        lines.extend(f"- {str(x).strip()}" for x in recurrent_tests if str(x).strip())
    elif single_episode_message:
        lines.append(f"- {single_episode_message}")
    else:
        lines.append("- Если эпизод единичный и лёгкий, обычно можно начать с наблюдения.")
    return "\n".join(lines).strip()


def _humanize_hypothesis_label(row: dict[str, Any]) -> str:
    label = str(row.get("label_ru") or row.get("name") or row.get("id") or "").strip()
    if not label:
        return ""
    if re.fullmatch(r"[a-z][a-z0-9_]*", label.lower()):
        return label.replace("_", " ")
    return label


def _anchor_terms_from_state(case_state: dict[str, Any]) -> list[str]:
    blob_parts = [
        str(case_state.get("chief_complaint") or ""),
        str(case_state.get("conversation_context") or ""),
        str(case_state.get("normalized_text") or ""),
    ]
    blob = " ".join(blob_parts).lower()
    blob = re.sub(r"[^\wа-яё ]+", " ", blob)
    tokens = [x for x in blob.split() if len(x) >= 4]
    seen: set[str] = set()
    out: list[str] = []
    for tok in tokens:
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
        if len(out) >= 8:
            break
    return out


def _urgent_markers_from_state(case_state: dict[str, Any]) -> list[str]:
    blob_parts = [
        str(case_state.get("chief_complaint") or ""),
        str(case_state.get("conversation_context") or ""),
        str(case_state.get("normalized_text") or ""),
    ]
    blob = " ".join(blob_parts).lower()
    markers: list[tuple[str, tuple[str, ...]]] = [
        ("боль в груди или выраженная тяжесть в грудной клетке", ("боль в груди", "давит в груди", "жжет в груди")),
        ("одышка или нехватка воздуха", ("одыш", "не хватает воздуха", "тяжело дыш")),
        ("обморок или предобморочное состояние", ("обмор", "предобмор", "теряю сознание")),
        ("кровь в рвоте или черный стул", ("кровь в рвоте", "черный стул", "чёрный стул", "мелена")),
        ("внезапная слабость/онемение в руке, ноге или лице", ("онем", "слабость в руке", "перекос лица", "не могу говорить")),
    ]
    out: list[str] = []
    for label, keys in markers:
        if any(k in blob for k in keys):
            out.append(label)
    return out


def _has_strong_urgent_signal(text: str) -> bool:
    t = str(text or "").lower()
    return any(
        k in t
        for k in (
            "боль в груди",
            "давит в груди",
            "одыш",
            "не хватает воздуха",
            "обмор",
            "теряю сознание",
            "кровь в рвоте",
            "черный стул",
            "чёрный стул",
            "сильная слабость",
            "перекос лица",
            "не могу говорить",
            "онемение",
            "внезапная слабость",
        )
    )


def _has_high_fever_with_systemic_signals(text: str) -> bool:
    t = str(text or "").lower().replace(",", ".")
    has_high_fever = False
    for hit in re.findall(r"\b(\d{2}(?:\.\d)?)\b", t):
        try:
            if float(hit) >= 39.0:
                has_high_fever = True
                break
        except Exception:
            continue
    if not has_high_fever and "39" in t and any(k in t for k in ("температур", "жар", "лихорад")):
        has_high_fever = True
    if not has_high_fever:
        return False
    systemic_hits = sum(
        1
        for k in ("сильная головная", "болит голова", "ломит", "слабость", "каш", "сопл", "горл", "озноб")
        if k in t
    )
    return systemic_hits >= 2


def _looks_febrile_respiratory(text: str) -> bool:
    t = str(text or "").lower().replace(",", ".")
    has_fever = any(k in t for k in ("температур", "лихорад", "жар", "39", "38"))
    resp_hits = sum(1 for k in ("каш", "сопл", "насморк", "горл", "мокрот", "одыш", "дых") if k in t)
    return has_fever and resp_hits >= 2


def _has_child_context(text: str) -> bool:
    t = str(text or "").lower()
    return any(k in t for k in ("ребен", "ребён", "ребенка", "ребёнка", "дет", "малыш", "педиатр"))


def _has_urinary_context(text: str) -> bool:
    t = str(text or "").lower()
    return any(k in t for k in ("моч", "цистит", "поясниц", "дизур", "жжение при мочеиспуск"))


def _derive_branch_from_case_state(case_state: dict[str, Any] | None) -> str:
    state = dict(case_state or {})
    text_blob = " ".join(
        [
            str(state.get("chief_complaint") or ""),
            str(state.get("conversation_context") or ""),
            str(state.get("normalized_text") or ""),
        ]
    )
    febrile_resp = _looks_febrile_respiratory(text_blob)
    child_ctx = _has_child_context(text_blob)
    urinary_ctx = _has_urinary_context(text_blob)
    scenario_id = str(state.get("primary_scenario_id") or "").strip().lower()
    if scenario_id:
        if febrile_resp and scenario_id.startswith("pediatric_") and not child_ctx:
            return "respiratory"
        if febrile_resp and scenario_id.startswith("urinary_") and not urinary_ctx:
            return "respiratory"
        for prefix in (
            "respiratory_",
            "gastro_",
            "cardio_",
            "neuro_",
            "urinary_",
            "allergy_",
            "orthopedics_",
            "oral_",
            "women_health_",
            "pediatric_",
            "ent_",
            "fatigue_",
        ):
            if scenario_id.startswith(prefix):
                return prefix.rstrip("_")
        if scenario_id in {"food_postmeal_branch"}:
            return "food_postmeal_branch"
    body_regions = [str(x).strip().lower() for x in (state.get("body_regions") or []) if str(x).strip()]
    if body_regions:
        first = body_regions[0]
        if first in {
            "respiratory",
            "gastro",
            "cardio",
            "neuro",
            "urinary",
            "allergy_skin",
            "oral_cavity",
            "fatigue_deficiency",
            "pleuritic_chest_dyspnea",
            "weight_loss_plateau",
        }:
            return first
        if first in {"knee", "ankle", "shoulder", "back", "orthopedics"}:
            return "orthopedics"
    evidence = {str(x).strip().lower() for x in (state.get("evidence_present") or []) if str(x).strip()}
    if {"cough", "sore_throat", "runny_nose", "sputum", "dyspnea", "fever"} & evidence:
        return "respiratory"
    if {"abdominal_pain", "vomiting", "diarrhea", "blood_in_stool"} & evidence:
        return "gastro"
    if "pleuritic_chest_dyspnea" in evidence:
        return "pleuritic_chest_dyspnea"
    if "weight_loss_plateau" in evidence:
        return "weight_loss_plateau"
    if {"chest_pain", "palpitations", "high_bp_context"} & evidence:
        return "cardio"
    if {"headache", "neurologic_deficit", "photophobia", "sudden_onset"} & evidence:
        return "neuro"
    if {"burning_urination", "urinary_frequency", "flank_pain", "hematuria"} & evidence:
        return "urinary"
    if {"rash", "itching", "angioedema_risk"} & evidence:
        return "allergy_skin"
    if febrile_resp:
        return "respiratory"
    return "default_triage"


def _apply_care_floor_by_scenario(
    *,
    current_care: str,
    scenario_id: str,
    user_blob: str,
) -> str:
    care = str(current_care or "").strip()
    sid = str(scenario_id or "").strip().lower()
    if care != "self_care_or_clarify":
        return care

    # Quality floor: these scenarios should not stay in pure self-care mode by default.
    floor_scenarios = {
        "neuro_migraine_like",
        "neuro_dizziness_vertigo",
        "gastro_diffuse_abdominal_pain",
        "gastro_nausea_vomiting",
        "fatigue_deficiency_fatigue_general",
        "orthopedics_foot_pain_morning",
    }
    if sid in floor_scenarios:
        return "routine_doctor"

    t = str(user_blob or "").lower()
    if any(k in t for k in ("рвот", "тошно", "головокруж", "сильная головная", "боль в животе")):
        return "routine_doctor"
    return care


def _ensure_minimum_patient_response(
    *,
    response_text: str,
    case_state: dict[str, Any] | None,
    followup_questions: list[str],
) -> str:
    state = dict(case_state or {})
    base = str(response_text or "").strip()
    if not state:
        return base

    low = base.lower()
    has_explanation = any(k in low for k in ("похоже", "вероят", "скорее", "причин"))
    has_actions = any(k in low for k in ("что делать", "пока можно", "рекоменд", "сейчас"))
    has_urgency = any(k in low for k in ("срочно", "103", "неотлож", "скорая", "опасн"))
    has_red_flags = bool(state.get("red_flags_detected"))
    too_short = len(base) < 220
    needs_upgrade = too_short or (not has_explanation) or (not has_actions) or (has_red_flags and not has_urgency)
    if not needs_upgrade:
        return base

    top_rows = list(state.get("top_hypotheses") or [])
    top_labels = [_humanize_hypothesis_label(x) for x in top_rows[:3]]
    top_labels = [x for x in top_labels if x]

    red_flags = [str(x).strip() for x in (state.get("red_flags_detected") or []) if str(x).strip()]
    care_level = str(state.get("care_level") or "").strip()

    user_anchor_terms = _anchor_terms_from_state(state)
    inferred_urgent = _urgent_markers_from_state(state)
    inferred_high_risk = bool(inferred_urgent)
    text_blob = " ".join(
        [
            str(state.get("chief_complaint") or ""),
            str(state.get("conversation_context") or ""),
            str(state.get("normalized_text") or ""),
        ]
    )
    febrile_respiratory = _looks_febrile_respiratory(text_blob)

    if care_level in {"urgent_review", "urgent_clinical_assessment"} or inferred_high_risk:
        action_steps = [
            "не откладывать очный осмотр сегодня",
            "до осмотра избегать нагрузок и следить за ухудшением симптомов",
        ]
    else:
        action_steps = [
            "наблюдать динамику симптомов в ближайшие 12-24 часа",
            "избегать провоцирующих факторов и поддерживать питьевой режим",
        ]

    urgent_lines = red_flags[:3] if red_flags else inferred_urgent[:3]
    if not urgent_lines:
        urgent_lines = [
        "резкое усиление боли или слабости",
        "одышка, боль в груди, обморок",
        "неукротимая рвота, кровь или черный стул",
        ]

    lines: list[str] = []
    if user_anchor_terms:
        lines.append("По вашему описанию ключевые признаки: " + ", ".join(user_anchor_terms[:3]) + ".")
    lines.append("Что вероятнее всего:")
    if top_labels:
        lines.append(f"- наиболее вероятно: {top_labels[0]}")
        for alt in top_labels[1:3]:
            lines.append(f"- также возможно: {alt}")
    else:
        lines.append("- пока данных недостаточно для точной версии, нужна короткая доуточняющая информация")

    lines.append("Что делать сейчас:")
    lines.extend(f"- {x}" for x in action_steps)

    lines.append("Когда срочно обращаться:")
    lines.extend(f"- {x}" for x in urgent_lines)

    question = next((str(q).strip() for q in (followup_questions or []) if str(q).strip()), "")
    if febrile_respiratory:
        question = "Есть ли одышка, боль в груди или выраженная слабость на фоне температуры?"
    if question:
        lines.append("Уточню один важный момент:")
        lines.append(f"- {question}")
    return "\n".join(lines).strip()


def _scenario_to_extractor_payload(primary_scenario: dict[str, Any] | None) -> dict[str, Any]:
    if not primary_scenario:
        return {}
    evidence_present: list[str] = []
    body_regions: list[str] = []
    evidence_unknown: list[str] = []
    scenario_id = str(primary_scenario.get("id", "")).lower()
    chief = str(primary_scenario.get("chief_complaint") or primary_scenario.get("title_ru") or "").strip()
    if "knee" in scenario_id:
        body_regions.append("knee")
    if "ankle" in scenario_id:
        body_regions.append("ankle")
    if "shoulder" in scenario_id:
        body_regions.append("shoulder")
    if "back" in scenario_id:
        body_regions.append("back")
    if "oral" in scenario_id or "tooth" in scenario_id or "gum" in scenario_id or "mouth" in scenario_id:
        body_regions.append("oral_cavity")
    for item in primary_scenario.get("must_ask", []) or []:
        t = str(item).lower()
        if "отек" in t or "отёк" in t:
            evidence_unknown.append("swelling")
        if "наступать" in t or "опираться" in t:
            evidence_unknown.append("cannot_bear_weight")
        if "температур" in t:
            evidence_unknown.append("fever")
        if "глотать" in t:
            evidence_unknown.append("trouble_swallowing")
        if "заклини" in t or "блок" in t:
            evidence_unknown.append("locking")
    return {
        "chief_complaint": chief,
        "evidence_present": evidence_present,
        "evidence_absent": [],
        "evidence_unknown": evidence_unknown,
        "body_regions": body_regions,
        "temporal_markers": [],
        "severity_hints": [],
    }


def _compose_structured_payload(
    *,
    state_dict: dict[str, Any],
    ranked: list[dict[str, Any]],
    red_flags: list[Any],
    next_questions: list[dict[str, Any]],
    care_level: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Собирает payload для compose_dynamic_response (unified reasoning)."""
    evidence_present = state_dict.get("evidence_present", []) or []
    self_care = list(policy.get("supportive_advice", []) or [])

    interpretation = ""
    contradictions = state_dict.get("contradictions") or {}
    if isinstance(contradictions, dict) and contradictions.get("changed"):
        interpretation = "С учётом новой информации ведущая версия изменилась, поэтому уточняю уже по новой ветке."

    top_hypotheses = []
    for item in ranked[:5]:
        top_hypotheses.append({
            "id": item.get("id") or item.get("code") or item.get("name") or "",
            "label_ru": item.get("label_ru") or item.get("name") or item.get("id") or "",
            "score": item.get("score") or item.get("diagnosis_score") or 0,
            "matched": item.get("matched") or [],
        })

    body_regions = state_dict.get("body_regions", []) or []
    return {
        "interpretation": interpretation,
        "top_hypotheses": top_hypotheses,
        "red_flags": red_flags,
        "next_questions": next_questions,
        "self_care": self_care,
        "care_level": care_level,
        "evidence_present": evidence_present,
        "body_regions": body_regions,
        "chief_complaint": str(state_dict.get("chief_complaint") or "").strip(),
        "user_message": str(state_dict.get("normalized_text") or "").strip(),
        "conversation_context": str(state_dict.get("conversation_context") or "").strip(),
    }


def _run_unified_reasoning_flow(
    *,
    consultation_state: Any,
    user_text: str,
    chat_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Unified reasoning: input_normalizer -> extract -> merge -> rank -> contradiction_check
    -> red_flags -> question_selector -> care_level -> recommendation_policy -> compose -> safety_filter.
    """
    result: dict[str, Any] = {
        "used_structured_flow": False,
        "structured_response": "",
        "primary_scenario": None,
        "ranked": [],
        "red_flags": [],
        "next_questions": [],
        "care_level": "",
        "policy": {},
        "contradictions": {},
    }
    if not user_text.strip():
        return result

    normalized_text = user_text
    try:
        norm_result = input_normalizer.normalize(user_text)
        if isinstance(norm_result, dict):
            normalized_text = norm_result.get("normalized_text") or user_text
        else:
            normalized_text = norm_result or user_text
    except Exception:
        normalized_text = user_text

    primary_scenario = None
    try:
        primary_scenario = scenario_router.resolve_primary_scenario(normalized_text)
    except Exception:
        primary_scenario = None
    result["primary_scenario"] = primary_scenario

    extractor_payload = {}
    if clinical_extractor and hasattr(clinical_extractor, "extract_clinical_evidence"):
        try:
            extractor_payload = clinical_extractor.extract_clinical_evidence(normalized_text, None) or {}
        except Exception:
            extractor_payload = {}
    if not extractor_payload and clinical_extractor and hasattr(clinical_extractor, "extract_evidence"):
        try:
            extractor_payload = clinical_extractor.extract_evidence(normalized_text) or {}
        except Exception:
            extractor_payload = {}

    scenario_payload = _scenario_to_extractor_payload(primary_scenario)
    merged_payload = {
        "chief_complaint": extractor_payload.get("chief_complaint") or scenario_payload.get("chief_complaint") or "",
        "evidence_present": (extractor_payload.get("evidence_present") or []) + (scenario_payload.get("evidence_present") or []),
        "evidence_absent": (extractor_payload.get("evidence_absent") or []) + (scenario_payload.get("evidence_absent") or []),
        "evidence_unknown": (extractor_payload.get("evidence_unknown") or []) + (scenario_payload.get("evidence_unknown") or []),
        "body_regions": (extractor_payload.get("body_regions") or []) + (scenario_payload.get("body_regions") or []),
        "temporal_markers": (extractor_payload.get("temporal_markers") or []) + (scenario_payload.get("temporal_markers") or []),
        "severity_hints": (extractor_payload.get("severity_hints") or []) + (scenario_payload.get("severity_hints") or []),
    }

    state_dict = dict(consultation_state) if isinstance(consultation_state, dict) else (consultation_state.model_dump() if hasattr(consultation_state, "model_dump") else dict(consultation_state))
    state_dict = case_state_manager.merge_extractor_output(state_dict, merged_payload)
    if primary_scenario:
        state_dict["primary_scenario_id"] = primary_scenario.get("id")
    state_dict = apply_scenario_branch_override(state_dict)
    state_dict["normalized_text"] = normalized_text
    state_dict["conversation_context"] = _conversation_user_blob(chat_history, normalized_text)

    ranked = []
    try:
        if hasattr(diagnostic_ranking_engine, "recalculate_from_case_state"):
            ranked = diagnostic_ranking_engine.recalculate_from_case_state(state_dict) or []
    except Exception:
        ranked = []

    contradictions = {}
    try:
        if hasattr(contradiction_checker, "check"):
            contradictions = contradiction_checker.check(state_dict, ranked) or {}
    except Exception:
        contradictions = {}
    state_dict["contradictions"] = contradictions

    red_flags = []
    try:
        if hasattr(red_flag_engine, "detect_red_flag_keys"):
            red_flags = list(red_flag_engine.detect_red_flag_keys(state_dict.get("evidence_present", [])) or [])
    except Exception:
        red_flags = []
    # Only evidence-based red flags for care_level; do not merge scenario's possible red_flags list

    next_questions = []
    try:
        if hasattr(question_selector, "select_best_questions"):
            next_questions = question_selector.select_best_questions(
                state_dict.get("evidence_present", []),
                state_dict.get("evidence_absent", []),
                state_dict.get("asked_questions", []),
                max_n=CONCIERGE_QUESTIONS_PER_REPLY,
            ) or []
    except Exception:
        pass
    if not next_questions and hasattr(question_selector, "select_best_questions_from_case_state"):
        try:
            next_questions = question_selector.select_best_questions_from_case_state(
                state_dict, max_n=CONCIERGE_QUESTIONS_PER_REPLY
            ) or []
        except Exception:
            pass
    if not next_questions and primary_scenario:
        must_ask = primary_scenario.get("must_ask", []) or []
        next_questions = [{"id": f"uq_{i+1}", "text": q} for i, q in enumerate(must_ask[:CONCIERGE_QUESTIONS_PER_REPLY]) if q]
    scenario_id = state_dict.get("primary_scenario_id") or (primary_scenario.get("id") if primary_scenario else "") or ""
    overridden_q = override_questions_by_scenario(
        scenario_id,
        [q.get("text") for q in next_questions] if next_questions else None,
        user_message=str(state_dict.get("conversation_context") or normalized_text or ""),
        evidence_present=state_dict.get("evidence_present"),
    )
    if overridden_q:
        next_questions = [{"id": f"uq_s_{i}", "text": t} for i, t in enumerate(overridden_q)]

    care_level = ""
    try:
        if hasattr(care_level_engine, "assign"):
            care_level = care_level_engine.assign(
                case_state=state_dict,
                red_flags=red_flags,
                hypotheses=ranked,
            ) or ""
    except Exception:
        care_level = ""
    if not care_level:
        care_level = "urgent_review" if red_flags else "self_care_or_clarify"
    care_level_before = care_level
    care_level_after_override = override_care_level_by_scenario(
        scenario_id,
        care_level_before,
        evidence_present=state_dict.get("evidence_present"),
        user_message=normalized_text or "",
    )
    if care_level_after_override != care_level_before:
        care_level = normalize_runner_care_level(care_level_after_override)
    else:
        care_level = normalize_care_level(care_level_before)
    _cal_detail, cal_runner = get_calibrated_care(
        scenario_id, care_level_before or care_level_after_override, care_level
    )
    if cal_runner != care_level:
        care_level = cal_runner

    policy = {}
    try:
        if hasattr(recommendation_policy, "build"):
            policy = recommendation_policy.build(
                case_state=state_dict,
                care_level=care_level,
                hypotheses=ranked,
                red_flags=red_flags,
            ) or {}
    except Exception:
        policy = {}

    compose_payload = _compose_structured_payload(
        state_dict=state_dict,
        ranked=ranked,
        red_flags=red_flags,
        next_questions=next_questions,
        care_level=care_level,
        policy=policy,
    )

    structured_response = ""
    try:
        if hasattr(response_composer, "compose_dynamic_response"):
            structured_response = response_composer.compose_dynamic_response(compose_payload) or ""
    except Exception:
        structured_response = ""

    try:
        if structured_response and hasattr(response_safety_filter, "clean"):
            structured_response = response_safety_filter.clean(
                response_text=structured_response,
                case_state=state_dict,
                policy=policy,
            ) or structured_response
    except Exception:
        pass

    update = {
        "chief_complaint": state_dict.get("chief_complaint", ""),
        "conversation_context": state_dict.get("conversation_context", ""),
        "conversation_stage": "red_flag_check" if red_flags else "clarify",
        "evidence_present": state_dict.get("evidence_present", []),
        "evidence_absent": state_dict.get("evidence_absent", []),
        "evidence_unknown": state_dict.get("evidence_unknown", []),
        "body_regions": state_dict.get("body_regions", []),
        "temporal_markers": state_dict.get("temporal_markers", []),
        "severity_hints": state_dict.get("severity_hints", []),
        "top_hypotheses": ranked[:5],
        "red_flags_detected": red_flags,
        "next_questions": next_questions[:3],
        "care_level": care_level,
        "contradictions": contradictions,
        "primary_scenario_id": primary_scenario.get("id") if primary_scenario else None,
        "last_clinical_update_reason": f"scenario_router:{primary_scenario.get('id', '')}" if primary_scenario else "unified_reasoning",
    }
    if isinstance(consultation_state, dict):
        consultation_state.update(update)
    elif hasattr(consultation_state, "__setattr__"):
        for field, value in update.items():
            try:
                setattr(consultation_state, field, value)
            except Exception:
                pass

    result.update({
        "used_structured_flow": bool(structured_response or ranked or primary_scenario),
        "structured_response": structured_response,
        "ranked": ranked,
        "red_flags": red_flags,
        "next_questions": next_questions,
        "care_level": care_level,
        "policy": policy,
        "contradictions": contradictions,
    })
    return result


def _run_structured_triage_flow(
    *,
    consultation_state: Any,
    user_text: str,
    chat_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Add-only structured triage layer.
    Returns a dict with optional keys:
      - used_structured_flow
      - primary_scenario
      - composed_response
      - top_hypotheses
      - next_questions
      - red_flags_detected
      - weight_strategy (user_type, strategy, plan — при ветке снижения веса)
    """
    result: dict[str, Any] = {
        "used_structured_flow": False,
        "primary_scenario": None,
        "composed_response": "",
        "top_hypotheses": [],
        "next_questions": [],
        "red_flags_detected": [],
        "weight_strategy": None,
    }
    if not user_text.strip():
        return result

    normalized_input = user_text
    try:
        norm_result = input_normalizer.normalize(user_text)
        if isinstance(norm_result, dict):
            normalized_input = norm_result.get("normalized_text") or user_text
        else:
            normalized_input = norm_result or user_text
    except Exception:
        normalized_input = user_text

    primary_scenario = None
    try:
        primary_scenario = scenario_router.resolve_primary_scenario(normalized_input)
    except Exception:
        primary_scenario = None
    result["primary_scenario"] = primary_scenario

    extractor_payload: dict[str, Any] = {}
    if clinical_extractor and hasattr(clinical_extractor, "extract_clinical_evidence"):
        try:
            extractor_payload = clinical_extractor.extract_clinical_evidence(normalized_input, []) or {}
        except Exception:
            extractor_payload = {}
    if not extractor_payload and clinical_extractor and hasattr(clinical_extractor, "extract_evidence"):
        try:
            extractor_payload = clinical_extractor.extract_evidence(normalized_input) or {}
        except Exception:
            extractor_payload = {}
    # Respiratory mild URI fallback: nose/throat/cough, no dyspnea -> respiratory_mild_uri
    br = extractor_payload.get("body_regions") or []
    ev_set = set(extractor_payload.get("evidence_present") or [])
    if primary_scenario and isinstance(primary_scenario, dict):
        if ("respiratory" in br or (br and str(br[0]).lower() == "respiratory")) and {"cough", "sore_throat", "runny_nose"} & ev_set and "dyspnea" not in ev_set:
            if "respiratory_mild_uri" not in str(primary_scenario.get("id") or ""):
                primary_scenario = {**primary_scenario, "id": "respiratory_mild_uri"}
    scenario_payload = _scenario_to_extractor_payload(primary_scenario)
    merged_payload = {
        "chief_complaint": extractor_payload.get("chief_complaint") or scenario_payload.get("chief_complaint") or "",
        "evidence_present": (extractor_payload.get("evidence_present") or []) + (scenario_payload.get("evidence_present") or []),
        "evidence_absent": (extractor_payload.get("evidence_absent") or []) + (scenario_payload.get("evidence_absent") or []),
        "evidence_unknown": (extractor_payload.get("evidence_unknown") or []) + (scenario_payload.get("evidence_unknown") or []),
        "body_regions": (extractor_payload.get("body_regions") or []) + (scenario_payload.get("body_regions") or []),
        "temporal_markers": (extractor_payload.get("temporal_markers") or []) + (scenario_payload.get("temporal_markers") or []),
        "severity_hints": (extractor_payload.get("severity_hints") or []) + (scenario_payload.get("severity_hints") or []),
    }

    state_dict = consultation_state if isinstance(consultation_state, dict) else (consultation_state.model_dump() if hasattr(consultation_state, "model_dump") else dict(consultation_state))
    state_dict = case_state_manager.merge_extractor_output(state_dict, merged_payload)
    if primary_scenario:
        state_dict["primary_scenario_id"] = primary_scenario.get("id")
    state_dict = apply_scenario_branch_override(state_dict)
    state_dict["normalized_text"] = normalized_input
    state_dict["conversation_context"] = _conversation_user_blob(chat_history, normalized_input)

    seeded_hypotheses: list[dict[str, Any]] = []
    if primary_scenario:
        hypotheses_raw = primary_scenario.get("hypotheses") or primary_scenario.get("likely_hypotheses") or []
        for idx, item in enumerate(hypotheses_raw):
            seeded_hypotheses.append({"id": str(item), "score": max(1, 100 - idx * 10), "matched": ["scenario_hint"]})

    ranked: list[dict[str, Any]] = []
    try:
        if hasattr(diagnostic_ranking_engine, "recalculate_from_case_state"):
            ranked = diagnostic_ranking_engine.recalculate_from_case_state(state_dict) or []
    except Exception:
        ranked = []
    if seeded_hypotheses and ranked:
        ranked_ids = {str(x.get("id")) for x in ranked}
        for item in reversed(seeded_hypotheses):
            if item["id"] not in ranked_ids:
                ranked.insert(0, item)
    elif seeded_hypotheses and not ranked:
        ranked = seeded_hypotheses
    state_dict["top_hypotheses"] = ranked[:5]

    red_flags: list[Any] = []
    try:
        if hasattr(red_flag_engine, "detect_red_flag_keys"):
            red_flags = list(red_flag_engine.detect_red_flag_keys(state_dict.get("evidence_present", [])) or [])
    except Exception:
        red_flags = []
    # Only evidence-based red flags; do not merge scenario's possible red_flags list
    state_dict["red_flags_detected"] = red_flags

    next_questions: list[dict[str, Any]] = []
    try:
        if hasattr(question_selector, "select_best_questions_from_case_state"):
            next_questions = question_selector.select_best_questions_from_case_state(state_dict) or []
    except Exception:
        next_questions = []
    if not next_questions and primary_scenario:
        must_ask = primary_scenario.get("must_ask", []) or []
        next_questions = [{"id": f"scenario_q_{i+1}", "text": q} for i, q in enumerate(must_ask[:3]) if q]
    scenario_id_str = (primary_scenario.get("id") if primary_scenario else "") or ""
    conv_blob = _conversation_user_blob(chat_history, user_text)
    overridden_q_str = override_questions_by_scenario(
        scenario_id_str,
        [q.get("text") for q in next_questions] if next_questions else None,
        user_message=conv_blob,
        evidence_present=state_dict.get("evidence_present"),
    )
    if overridden_q_str:
        next_questions = [{"id": f"scenario_q_{i}", "text": t} for i, t in enumerate(overridden_q_str)]
    state_dict["next_questions"] = next_questions[:CONCIERGE_QUESTIONS_PER_REPLY]

    primary_scope = str(
        state_dict.get("primary_scope")
        or state_dict.get("normalized_complaint")
        or extractor_payload.get("primary_scope")
        or (state_dict.get("body_regions") or [""])[0]
        or ""
    ).strip().lower()
    if primary_scope in ("knee", "ankle", "shoulder", "back"):
        primary_scope = "orthopedics"
    care_level_detail = ""
    try:
        if hasattr(care_level_engine, "decide_care_level"):
            care_level_detail = care_level_engine.decide_care_level(
                ranked or [],
                red_flags,
                evidence_present=state_dict.get("evidence_present"),
                normalized_complaint=primary_scope or "",
                user_message=normalized_input or "",
            ) or ""
    except Exception:
        pass
    if not care_level_detail:
        care_level_detail = "urgent_review" if red_flags else "self_care_or_clarify"
    if primary_scenario:
        state_dict["primary_scenario_id"] = primary_scenario.get("id")
        state_dict["last_clinical_update_reason"] = f"scenario_router:{primary_scenario.get('id', '')}"
    care_level_detail = override_care_level_by_scenario(
        state_dict.get("primary_scenario_id") or "",
        care_level_detail,
        evidence_present=state_dict.get("evidence_present"),
        user_message=normalized_input or "",
    )
    state_dict["care_level_detail"] = care_level_detail
    state_dict["care_level"] = normalize_runner_care_level(care_level_detail)
    _cal_detail, cal_runner = get_calibrated_care(
        state_dict.get("primary_scenario_id") or "",
        care_level_detail,
        state_dict.get("care_level") or "",
    )
    if cal_runner != (state_dict.get("care_level") or ""):
        state_dict["care_level"] = cal_runner
    if not state_dict.get("conversation_stage"):
        if red_flags:
            state_dict["conversation_stage"] = "red_flag_check"
        elif ranked:
            state_dict["conversation_stage"] = "clarify"
        else:
            state_dict["conversation_stage"] = "intake"

    try:
        change_info = contradiction_checker.check(state_dict, ranked)
        if change_info.get("reason"):
            state_dict["last_clinical_update_reason"] = change_info.get("reason", "")
    except Exception:
        pass

    policy: dict[str, Any] = {}
    try:
        if hasattr(recommendation_policy, "build"):
            policy = recommendation_policy.build(
                case_state=state_dict,
                care_level=state_dict.get("care_level_detail") or state_dict.get("care_level", ""),
                hypotheses=ranked,
                red_flags=red_flags,
            )
    except Exception:
        pass

    composed = ""
    try:
        if hasattr(response_composer, "compose_from_case_state"):
            composed = response_composer.compose_from_case_state(state_dict) or ""
    except Exception:
        composed = ""
    if not composed and primary_scenario:
        intro = "Понял."
        if primary_scenario.get("chief_complaint") or primary_scenario.get("title_ru"):
            intro += f"\nПохоже, сейчас мы идём по ветке: {primary_scenario.get('title_ru') or primary_scenario.get('chief_complaint')}."
        q_text = "\n".join(f"- {x.get('text', '')}" for x in next_questions[:CONCIERGE_QUESTIONS_PER_REPLY] if x.get("text"))
        composed = f"{intro}\n\nЧтобы понять точнее, уточню:\n{q_text}".strip()

    try:
        if composed and hasattr(response_safety_filter, "clean"):
            composed = response_safety_filter.clean(
                response_text=composed,
                case_state=state_dict,
                policy=policy,
            ) or composed
    except Exception:
        pass

    if hasattr(consultation_state, "__setattr__") and not isinstance(consultation_state, dict):
        for field in (
            "chief_complaint", "conversation_stage", "evidence_present", "evidence_absent", "evidence_unknown",
            "body_regions", "temporal_markers", "severity_hints", "top_hypotheses", "red_flags_detected",
            "next_questions", "care_level",
        ):
            if field in state_dict:
                try:
                    setattr(consultation_state, field, state_dict[field])
                except Exception:
                    pass

    result["used_structured_flow"] = bool(composed or ranked or primary_scenario)
    result["composed_response"] = composed
    result["top_hypotheses"] = state_dict.get("top_hypotheses", [])
    result["next_questions"] = state_dict.get("next_questions", [])
    result["red_flags_detected"] = state_dict.get("red_flags_detected", [])
    brs_l = [str(x).strip().lower() for x in (state_dict.get("body_regions") or []) if str(x).strip()]
    evp_l = [str(x).strip().lower() for x in (state_dict.get("evidence_present") or []) if str(x).strip()]
    if "weight_loss_plateau" in brs_l or "weight_loss_plateau" in evp_l:
        try:
            from app.services.weight_strategy_engine import build_weight_loss_strategy_struct

            result["weight_strategy"] = build_weight_loss_strategy_struct(state_dict)
        except Exception:
            result["weight_strategy"] = None
    return result


def _normalize_slot_name(question: str) -> str:
    q = (question or "").lower()
    if any(k in q for k in ("как давно", "когда", "начал", "длительность")):
        return "onset_timeline"
    if any(k in q for k in ("температур", "озноб", "лихорад")):
        return "fever_infection"
    if any(k in q for k in ("кашель", "горле", "одыш", "слабост", "тошнот", "рвот", "стул", "зуд", "сып")):
        return "core_symptoms"
    if any(k in q for k in ("принимал", "препарат", "леч", "эффект")):
        return "self_treatment_response"
    if any(k in q for k in ("хроническ", "аллерг")):
        return "history_allergies"
    if any(k in q for k in ("где именно", "локал", "одна сторона", "размер")):
        return "location_character"
    if any(k in q for k in ("после чего", "контакт", "связь", "съели", "выпили")):
        return "trigger_exposure"
    return re.sub(r"[^a-zа-я0-9]+", "_", q).strip("_")[:48] or "generic_context"


def _assistant_asked_questions(chat_history: list[dict[str, Any]]) -> list[str]:
    """Строки, похожие на уже заданные вопросы (в т.ч. маркеры без «?» в конце строки)."""
    asked: list[str] = []
    question_starts = (
        "есть ли ",
        "была ли ",
        "было ли ",
        "как давно ",
        "когда ",
        "какой ",
        "какая ",
        "какие ",
        "что именно ",
        "удалось ли ",
        "принимал",
        "делали ли ",
    )
    for item in chat_history or []:
        if (item or {}).get("role") != "assistant":
            continue
        content = str((item or {}).get("content") or "")
        for line in content.splitlines():
            s = re.sub(r"^[\-\*\d\.\)\s]+", "", line).strip()
            if not s or len(s) < 12:
                continue
            low = s.lower()
            if s.endswith("?") and s not in asked:
                asked.append(s)
                continue
            if len(s) >= 28 and any(low.startswith(p) for p in question_starts) and s not in asked:
                asked.append(s)
    return asked


def _collect_facts(text: str, profile: Optional[dict[str, Any]] = None) -> dict[str, str]:
    low = (text or "").lower()
    facts: dict[str, str] = {}
    if any(k in low for k in ("день", "дня", "недел", "месяц", "час", "сегодня", "вчера")):
        facts["onset_timeline"] = "mentioned"
    if any(k in low for k in ("температур", "озноб", "лихорад", "39", "38", "37")):
        facts["fever_infection"] = "mentioned"
    if any(k in low for k in ("каш", "горл", "одыш", "слаб", "сып", "зуд", "боль", "тошн", "рвот", "понос", "стул", "голов")):
        facts["core_symptoms"] = "mentioned"
    if any(k in low for k in ("прин", "пил", "пила", "ибупроф", "парацет", "таблет", "лечил", "мазал")):
        facts["self_treatment_response"] = "mentioned"
    if any(k in low for k in ("аллерг", "неперенос")):
        facts["history_allergies"] = "mentioned"
    if any(k in low for k in ("слева", "справа", "живот", "голова", "горло", "груд", "рук", "ног", "лицо", "кожа")):
        facts["location_character"] = "mentioned"
    if any(k in low for k in ("после", "контакт", "съел", "съела", "выпил", "еда", "лекарств", "продукт")):
        facts["trigger_exposure"] = "mentioned"
    if profile:
        if profile.get("allergies") or profile.get("chronic_conditions"):
            facts["history_allergies"] = "profile"
    return facts


def build_consultation_state(
    *,
    user_message: str,
    chat_history: list[dict[str, Any]],
    profile: Optional[dict[str, Any]] = None,
    structured: Optional[dict[str, Any]] = None,
    complaint_protocol: Optional[dict[str, Any]] = None,
    complaint_meta: Optional[dict[str, Any]] = None,
    strict_protocol: Optional[dict[str, Any]] = None,
    has_lab_data: bool = False,
) -> ConsultationStateSnapshot:
    complaint = complaint_protocol if isinstance(complaint_protocol, dict) else {}
    protocol = strict_protocol if isinstance(strict_protocol, dict) else {}
    anamnesis = [str(x).strip() for x in (complaint.get("anamnesis_questions") or []) if str(x).strip()]
    if not anamnesis:
        anamnesis = [str(x).strip() for x in (protocol.get("anamnesis") or []) if str(x).strip()]
    required_fields = [_normalize_slot_name(q) for q in anamnesis[:6]]
    asked_questions = _assistant_asked_questions(chat_history)
    facts = _collect_facts(user_message, profile)

    for item in chat_history[-8:]:
        if (item or {}).get("role") == "user":
            facts.update(_collect_facts(str((item or {}).get("content") or ""), profile=None))

    if isinstance(structured, dict):
        if structured.get("chief_complaint"):
            facts["chief_complaint"] = "structured"
        if structured.get("missing_information"):
            for x in structured.get("missing_information") or []:
                slot = _normalize_slot_name(str(x))
                if slot not in required_fields:
                    required_fields.append(slot)
        if structured.get("top_hypotheses"):
            facts["hypotheses_available"] = "structured"

    missing_fields = [slot for slot in required_fields if slot and slot not in facts]

    next_question = None
    for question in anamnesis:
        if question in asked_questions:
            continue
        slot = _normalize_slot_name(question)
        if slot in missing_fields:
            next_question = question
            break

    if not next_question and anamnesis:
        for question in anamnesis:
            if question not in asked_questions:
                next_question = question
                break

    can_conclude = not missing_fields or (has_lab_data and len(facts) >= 2)
    clar_rounds_done = count_assistant_clarification_rounds(chat_history)
    if clar_rounds_done >= MAX_CLARIFICATION_ROUNDS:
        can_conclude = True
        missing_fields = []
        next_question = None
    severity = str((structured or {}).get("severity") or "YELLOW").upper()
    suggested_labs = [str(x).strip() for x in (complaint.get("suggested_labs") or []) if str(x).strip()]
    nutrition_recommendations = [str(x).strip() for x in (complaint.get("nutrition_recommendations") or []) if str(x).strip()]
    physical = [str(x).strip() for x in (complaint.get("physical_exercise_prevention_rehabilitation") or []) if str(x).strip()]
    meta = complaint_meta if isinstance(complaint_meta, dict) else {}

    case_state: Optional[dict[str, Any]] = None
    try:
        response_from_triage, case_state = run_stateful_triage(
            user_message=user_message,
            chat_history=chat_history,
            previous_case_state=None,
        )
        if response_from_triage and case_state:
            case_state = case_state
    except Exception:
        case_state = None

    snapshot = ConsultationStateSnapshot(
        complaint=str((structured or {}).get("chief_complaint") or complaint.get("complaint") or protocol.get("title") or user_message).strip(),
        protocol_source="complaint" if complaint else ("strict_protocol" if protocol else "general"),
        severity=severity if severity in ("GREEN", "YELLOW", "RED") else "YELLOW",
        required_fields=required_fields,
        collected_facts=facts,
        missing_fields=missing_fields,
        last_follow_up_question=next_question,
        can_conclude=can_conclude,
        suggested_labs=suggested_labs,
        nutrition_recommendations=nutrition_recommendations,
        physical_exercise_prevention_rehabilitation=physical,
        dialogue_meta=dict(meta.get("dialogue_meta") or {}),
        labs_meta=dict(meta.get("labs_meta") or {}),
        seasonality=dict(meta.get("seasonality") or {}),
        market_signal_cluster=str(meta.get("market_signal_cluster") or ""),
        public_source_basis=[str(x).strip() for x in (meta.get("public_source_basis") or []) if str(x).strip()],
        case_state=case_state,
    )
    return snapshot


def run_stateful_triage(
    *,
    user_message: str,
    chat_history: list[dict[str, Any]],
    previous_case_state: Optional[dict[str, Any]] = None,
) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    """
    Triage pipeline: structured flow first (scenario + case_state + ranking + compose), then fallback to extractor-based flow.
    """
    user_text = _normalize_user_text_for_triage(_safe_user_text(user_message))
    case_state = dict(previous_case_state) if previous_case_state else {}

    # Specialized branch routing (food/post-meal) - soft integration.
    try:
        specialized_branch = routing_control.detect_specialized_branch(
            user_text,
            medical_relevance_filter=_medical_relevance_filter,
        )
    except Exception:
        specialized_branch = None
    if specialized_branch in {"food_postmeal_branch", None}:
        food_text, food_case_state = _try_food_branch(
            user_text=user_text,
            previous_case_state=case_state,
        )
        if food_text:
            return (food_text, food_case_state or case_state)
    elif _unified_master_triage:
        try:
            master_result = _unified_master_triage.triage(
                user_text=user_text,
                symptoms=[],
                recurrent=bool(case_state.get("food_recurrent", False)),
                preferred_route_id=specialized_branch,
            )
            if master_result.matched:
                payload = dict(master_result.triage_payload or {})
                case_state["master_branch_payload"] = payload
                case_state["primary_scenario_id"] = master_result.route_id
                case_state["last_clinical_update_reason"] = f"specialized_branch:{master_result.route_id}"
                case_state["conversation_stage"] = "specialized_master"
                return (_render_unified_master_response(payload), case_state)
        except Exception:
            pass

    # ----- Unified reasoning flow (prefer if returns response) -----
    unified_result: dict[str, Any] = {}
    try:
        unified_result = _run_unified_reasoning_flow(
            consultation_state=case_state,
            user_text=user_text,
            chat_history=chat_history or [],
        )
    except Exception:
        unified_result = {}
    unified_response = (unified_result or {}).get("structured_response", "").strip()
    if unified_response:
        # 44: force respiratory_mild_uri when unified flow returns but case is mild respiratory
        try:
            if clinical_extractor and hasattr(clinical_extractor, "extract_clinical_evidence"):
                ext = clinical_extractor.extract_clinical_evidence(user_text or "", []) or {}
                br = ext.get("body_regions") or []
                ev = set(ext.get("evidence_present") or [])
                if ("respiratory" in br or (br and str(br[0]).lower() == "respiratory")) and {"cough", "sore_throat", "runny_nose"} & ev and "dyspnea" not in ev:
                    case_state["primary_scenario_id"] = "respiratory_mild_uri"
                    case_state["last_clinical_update_reason"] = "scenario_router:respiratory_mild_uri"
                    if not case_state.get("body_regions"):
                        case_state["body_regions"] = ["respiratory"]
        except Exception:
            pass
        return (unified_response, case_state)

    # =========================
    # STAGE1 STRUCTURED TRIAGE
    # safe additive layer
    # =========================
    structured_result: dict[str, Any] = {}
    try:
        structured_result = _run_structured_triage_flow(
            consultation_state=case_state,
            user_text=user_text,
            chat_history=chat_history or [],
        )
    except Exception:
        structured_result = {}

    structured_response = (structured_result or {}).get("composed_response", "").strip()
    if structured_response:
        primary_scenario = (structured_result or {}).get("primary_scenario")
        if primary_scenario:
            try:
                case_state["primary_scenario_id"] = primary_scenario.get("id")
                case_state["last_clinical_update_reason"] = f"scenario_router:{primary_scenario.get('id', '')}"
            except Exception:
                pass
        case_state = apply_scenario_branch_override(case_state)
        ws = (structured_result or {}).get("weight_strategy")
        if ws:
            case_state["weight_strategy"] = ws
        return (structured_response, case_state)

    # Fallback: existing extractor -> ranking -> compose pipeline
    try:
        if not clinical_extractor or not hasattr(clinical_extractor, "extract_clinical_evidence"):
            return (None, case_state)
        extracted = clinical_extractor.extract_clinical_evidence(user_message or "", chat_history)
        evidence_present = extracted.get("evidence_present") or []
        body_regions = extracted.get("body_regions") or []
        if not evidence_present and not body_regions:
            return (None, case_state)

        case_state_manager.merge_extractor_output(case_state, extracted)
        scenario_match = scenario_router.resolve_primary_scenario(user_message or "")
        if scenario_match:
            case_state["scenario_match"] = scenario_match

        case_state["top_hypotheses"] = diagnostic_ranking_engine.recalculate_from_case_state(case_state)
        pruned = diagnostic_ranking_engine.prune_low_confidence(case_state["top_hypotheses"], threshold=0.15)
        if not pruned and not evidence_present:
            return (None, case_state)
        case_state["top_hypotheses"] = pruned[:5]
        case_state["red_flags_detected"] = red_flag_engine.detect_red_flag_keys(case_state.get("evidence_present") or [])
        case_state["next_questions"] = question_selector.select_best_questions_from_case_state(
            case_state, max_n=CONCIERGE_QUESTIONS_PER_REPLY
        )
        response_text = response_composer.compose_from_case_state_simple(case_state)
        if not (response_text or "").strip():
            return (None, case_state)
        return (response_text.strip(), case_state)
    except Exception:
        return (None, None)


class ConsultationOrchestratorAdapter:
    """
    Class-style facade over functional triage pipeline.
    Exposes orchestrator-friendly API:
      run_consultation(user_id=..., user_text=..., debug=..., extra_context=...)
    """

    def __init__(
        self,
        *,
        user_store: Any | None = None,
        medical_relevance_filter: Any | None = None,
        routing_control_module: Any | None = None,
        food_branch: Any | None = None,
    ) -> None:
        self.user_store = user_store or user_store_service
        self.medical_relevance_filter = medical_relevance_filter or _medical_relevance_filter
        self.routing_control = routing_control_module or routing_control
        self.food_branch = food_branch or (ZaZFoodBranchIntegration() if ZaZFoodBranchIntegration else None)

    def _try_food_branch(
        self,
        *,
        user_id: str | None,
        user_text: str,
        recurrent: bool = False,
        debug: bool = False,
        ask_followups: bool = True,
        doctor_safe: bool = True,
        food_journal_entries: list[dict[str, Any]] | None = None,
        extra_context: dict[str, Any] | None = None,
    ) -> Any | None:
        if not self.food_branch or not FoodBranchInput:
            return None

        memory_state = None
        if self.user_store and user_id and hasattr(self.user_store, "get_branch_memory"):
            try:
                memory_state = self.user_store.get_branch_memory(user_id, "food_postmeal_branch")
            except Exception:
                memory_state = None

        branch_input = FoodBranchInput(
            user_text=user_text,
            user_id=user_id,
            recurrent=recurrent,
            debug=debug,
            ask_followups=ask_followups,
            doctor_safe=doctor_safe,
            memory_state=memory_state,
            food_journal_entries=food_journal_entries or [],
            extra_context=extra_context or {},
        )

        result = self.food_branch.handle(branch_input)
        if getattr(result, "matched", False) and self.user_store and user_id and hasattr(self.user_store, "set_branch_memory"):
            try:
                self.user_store.set_branch_memory(
                    user_id,
                    "food_postmeal_branch",
                    result.memory_state,
                )
            except Exception:
                pass
        return result

    def _run_default_consultation_flow(
        self,
        *,
        user_id: str | None,
        user_text: str,
        debug: bool = False,
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = debug
        extra_context = extra_context or {}
        chat_history = list(extra_context.get("chat_history", []) or [])

        previous_case_state = {}
        if self.user_store and user_id and hasattr(self.user_store, "get_consultation_state"):
            try:
                previous_case_state = dict(self.user_store.get_consultation_state(user_id) or {})
            except Exception:
                previous_case_state = {}

        triage_text, case_state = run_stateful_triage(
            user_message=user_text,
            chat_history=chat_history,
            previous_case_state=previous_case_state,
        )

        if self.user_store and user_id and case_state and hasattr(self.user_store, "save_consultation_state"):
            try:
                self.user_store.save_consultation_state(user_id, case_state)
            except Exception:
                pass

        followups = list((case_state or {}).get("next_questions") or [])
        followup_questions = []
        for item in followups[:3]:
            if isinstance(item, dict) and item.get("text"):
                followup_questions.append(str(item.get("text")))
            elif isinstance(item, str):
                followup_questions.append(item)

        patient_response = _ensure_minimum_patient_response(
            response_text=(triage_text or "").strip(),
            case_state=case_state or {},
            followup_questions=followup_questions,
        )
        current_care = str((case_state or {}).get("care_level", "")).strip()
        if current_care == "self_care_or_clarify":
            user_blob = " ".join(
                [
                    str(user_text or ""),
                    str((case_state or {}).get("conversation_context") or ""),
                ]
            )
            if _has_strong_urgent_signal(user_blob) or _has_high_fever_with_systemic_signals(user_blob):
                current_care = "urgent_review"
                if isinstance(case_state, dict):
                    case_state["care_level"] = current_care
        current_care = _apply_care_floor_by_scenario(
            current_care=current_care,
            scenario_id=str((case_state or {}).get("primary_scenario_id") or ""),
            user_blob=" ".join(
                [
                    str(user_text or ""),
                    str((case_state or {}).get("conversation_context") or ""),
                ]
            ),
        )
        if isinstance(case_state, dict):
            case_state["care_level"] = current_care

        return {
            "branch": _derive_branch_from_case_state(case_state),
            "matched": bool(triage_text),
            "relevance_score": 0.0,
            "patient_response": patient_response,
            "doctor_payload": {
                "primary_scenario_id": (case_state or {}).get("primary_scenario_id", ""),
                "care_level": current_care,
                "top_hypotheses": (case_state or {}).get("top_hypotheses", []),
                "red_flags_detected": (case_state or {}).get("red_flags_detected", []),
            },
            "care_level": current_care,
            "followup_questions": followup_questions,
            "machine_payload": {"case_state": case_state or {}},
            "errors": [],
        }

    def run_consultation(
        self,
        *,
        user_id: str | None,
        user_text: str,
        debug: bool = False,
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        extra_context = extra_context or {}

        user_text = _normalize_user_text_for_triage(user_text)
        recurrent = bool(extra_context.get("recurrent", False))
        ask_followups = bool(extra_context.get("ask_followups", True))
        doctor_safe = bool(extra_context.get("doctor_safe", True))
        food_journal_entries = list(extra_context.get("food_journal_entries", []) or [])

        specialized_branch = None
        if self.routing_control and hasattr(self.routing_control, "detect_specialized_branch"):
            try:
                specialized_branch = self.routing_control.detect_specialized_branch(
                    user_text,
                    medical_relevance_filter=self.medical_relevance_filter,
                )
            except Exception:
                specialized_branch = None

        if specialized_branch == "food_postmeal_branch" or specialized_branch is None:
            food_result = self._try_food_branch(
                user_id=user_id,
                user_text=user_text,
                recurrent=recurrent,
                debug=debug,
                ask_followups=ask_followups,
                doctor_safe=doctor_safe,
                food_journal_entries=food_journal_entries,
                extra_context=extra_context,
            )
            if food_result and getattr(food_result, "matched", False):
                return {
                    "branch": food_result.branch_name,
                    "matched": True,
                    "relevance_score": food_result.relevance_score,
                    "patient_response": food_result.patient_safe_text,
                    "doctor_payload": food_result.doctor_safe_json,
                    "care_level": food_result.care_level,
                    "followup_questions": food_result.followup_questions,
                    "machine_payload": food_result.machine_payload,
                    "errors": food_result.errors,
                }
        elif _unified_master_triage:
            try:
                master_result = _unified_master_triage.triage(
                    user_text=user_text,
                    symptoms=[],
                    recurrent=recurrent,
                    preferred_route_id=specialized_branch,
                )
                if master_result.matched:
                    payload = dict(master_result.triage_payload or {})
                    return {
                        "branch": master_result.route_id or "unified_master_route",
                        "matched": True,
                        "relevance_score": float(master_result.confidence),
                        "patient_response": _render_unified_master_response(payload),
                        "doctor_payload": payload,
                        "care_level": "urgent_review" if payload.get("red_flags_detected") else "self_care_or_clarify",
                        "followup_questions": [],
                        "machine_payload": {"master_triage": payload, "reasons": master_result.reasons},
                        "errors": [],
                    }
            except Exception:
                pass

        return self._run_default_consultation_flow(
            user_id=user_id,
            user_text=user_text,
            debug=debug,
            extra_context=extra_context,
        )
