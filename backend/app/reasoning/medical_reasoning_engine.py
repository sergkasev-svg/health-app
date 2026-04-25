from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from app.services.diagnostic_ranking_engine import update_hypothesis
from app.services.clinical_extractor import extract_clinical_evidence
from app.services.red_flag_engine import detect_red_flags as detect_structured_red_flags
from app.services.question_selector import select_best_questions
from app.services.care_level_engine import decide_care_level, normalize_runner_care_level
from app.services.recommendation_engine import build_recommendations
from app.services.contradiction_checker import detect_contradictions
from app.services.response_composer import compose_dynamic_response
from app.services.scenario_care_overrides import override_care_level_by_scenario
from app.services.scenario_question_overrides import override_questions_by_scenario


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SHARED_RULES_FILE = _PROJECT_ROOT / "medical_knowledge" / "shared" / "shared_rules.json"
_DISEASE_SCRIPTS_DIR = _PROJECT_ROOT / "medical_knowledge" / "diseases"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


@lru_cache(maxsize=1)
def _load_shared_rules() -> dict[str, Any]:
    try:
        if _SHARED_RULES_FILE.exists():
            payload = json.loads(_SHARED_RULES_FILE.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
    except Exception:
        return {}
    return {}


@lru_cache(maxsize=1)
def _load_disease_scripts() -> list[dict[str, Any]]:
    if not _DISEASE_SCRIPTS_DIR.exists():
        return []
    out: list[dict[str, Any]] = []
    for fp in sorted(_DISEASE_SCRIPTS_DIR.glob("disease_*.json")):
        try:
            item = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def _detect_red_flags(user_message: str, complaint_protocol: dict[str, Any], symptom_severity_context: dict[str, Any]) -> list[str]:
    msg = _norm(user_message)
    hits: list[str] = []
    local_flags = [
        str(x).strip()
        for x in (
            complaint_protocol.get("red_flags_specific")
            or complaint_protocol.get("red_flags")
            or []
        )
        if str(x).strip()
    ]
    shared_flags = [
        str(x).strip()
        for x in (_load_shared_rules().get("shared_red_flags") or [])
        if str(x).strip()
    ]
    for fl in local_flags + shared_flags:
        token = _norm(fl)
        if token and token in msg:
            hits.append(fl)
    for fl in (symptom_severity_context.get("red_flag_matches") or []):
        s = str(fl).strip()
        if s:
            hits.append(s)
    # explicit high-risk patterns
    if any(x in msg for x in ("отек губ", "отёк губ", "отек языка", "отёк языка", "одышка", "не хватает воздуха")):
        hits.append("allergy_respiratory_risk")
    if any(x in msg for x in ("внезапная очень сильная головная боль", "самая сильная головная боль")):
        hits.append("thunderclap_headache_risk")
    dedup: list[str] = []
    seen: set[str] = set()
    for h in hits:
        k = _norm(h)
        if not k or k in seen:
            continue
        seen.add(k)
        dedup.append(h)
    return dedup


def _extract_labs_signal(user_message: str, lab_context: dict[str, Any]) -> dict[str, str]:
    msg = _norm(user_message)
    out: dict[str, str] = {}
    m_hgb = re.search(r"(гемоглобин|hgb)\s*[:=]?\s*(\d{2,3})", msg)
    if m_hgb:
        try:
            v = int(m_hgb.group(2))
            out["hgb"] = "low" if v < 120 else "normal_or_high"
        except Exception:
            pass
    if any(x in msg for x in ("ферритин", "ferritin")):
        out["ferritin"] = "mentioned"
    if any(x in msg for x in ("лейкоцит", "leukocyte", "лейк")) and any(x in msg for x in ("моч", "urine")):
        out["urine_leukocytes"] = "possibly_high"
    if (lab_context or {}).get("suggested_tests"):
        out["labs_present"] = "true"
    return out


def _match_disease_candidates(user_message: str, complaint_protocol: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    msg = _norm(user_message)
    complaint_blob = " ".join(
        [
            str(complaint_protocol.get("name") or complaint_protocol.get("complaint") or ""),
            " ".join(str(x) for x in (complaint_protocol.get("key_symptoms") or [])),
            " ".join(str(x) for x in (complaint_protocol.get("common_user_phrasings") or [])),
        ]
    ).lower()
    scored: list[tuple[float, dict[str, Any]]] = []
    for d in _load_disease_scripts():
        name = str(d.get("name") or "").strip()
        if not name:
            continue
        keys = [name] + [str(x) for x in (d.get("user_phrases") or [])] + [str(x) for x in (d.get("key_symptoms") or [])]
        hay = " ".join(keys).lower()
        score = 0.0
        for w in re.findall(r"[а-яёa-z0-9]+", msg):
            if len(w) < 3:
                continue
            if w in hay:
                score += 1.0
        for w in re.findall(r"[а-яёa-z0-9]+", complaint_blob):
            if len(w) < 3:
                continue
            if w in hay:
                score += 0.5
        if score > 0:
            scored.append((score, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[dict[str, Any]] = []
    for s, d in scored[:limit]:
        out.append({"label": str(d.get("name") or ""), "confidence": min(0.92, 0.45 + s / 12.0)})
    return out


def _is_complaint_relevant(user_message: str, complaint_protocol: dict[str, Any]) -> bool:
    msg = _norm(user_message)
    if not msg or not isinstance(complaint_protocol, dict) or not complaint_protocol:
        return False
    lexical: list[str] = []
    for key in ("name", "complaint", "id"):
        v = str(complaint_protocol.get(key) or "").strip()
        if v:
            lexical.append(v)
    for key in ("common_user_phrasings", "user_phrases", "aliases", "keywords"):
        lexical.extend([str(x).strip() for x in (complaint_protocol.get(key) or []) if str(x).strip()])
    for p in lexical:
        if len(p) >= 4 and _norm(p) in msg:
            return True
    msg_tokens = {w for w in re.findall(r"[а-яёa-z0-9]+", msg) if len(w) >= 4}
    lex_tokens: set[str] = set()
    for p in lexical:
        for w in re.findall(r"[а-яёa-z0-9]+", _norm(p)):
            if len(w) >= 4:
                lex_tokens.add(w)
    if not lex_tokens:
        return False
    overlap = msg_tokens & lex_tokens
    return len(overlap) >= 2


def build_medical_reasoning_output(
    *,
    user_message: str,
    complaint_protocol: dict[str, Any] | None,
    food_trigger_context: dict[str, Any] | None,
    lab_context: dict[str, Any] | None,
    symptom_severity_context: dict[str, Any] | None,
    followup_questions: list[str] | None = None,
    reasoning_graph_context: dict[str, Any] | None = None,
    chat_history: list[Any] | None = None,
    primary_scenario_id: str | None = None,
) -> dict[str, Any]:
    complaint = complaint_protocol if isinstance(complaint_protocol, dict) else {}
    food_ctx = food_trigger_context if isinstance(food_trigger_context, dict) else {}
    labs_ctx = lab_context if isinstance(lab_context, dict) else {}
    sev_ctx = symptom_severity_context if isinstance(symptom_severity_context, dict) else {}
    rg_ctx = reasoning_graph_context if isinstance(reasoning_graph_context, dict) else {}
    msg = _norm(user_message)
    complaint_is_relevant = _is_complaint_relevant(user_message, complaint)
    history_text = " ".join(
        [
            str((x or {}).get("content") or (x or {}).get("text") or x or "").strip()
            for x in (chat_history or [])
        ]
    ).strip()
    iterative_state = update_hypothesis({}, (history_text + " " + str(user_message or "")).strip())
    extracted = extract_clinical_evidence(user_message or "", chat_history=chat_history or [])
    evidence_present = [str(x).strip() for x in (extracted.get("evidence_present") or []) if str(x).strip()]
    evidence_absent = [str(x).strip() for x in (extracted.get("evidence_absent") or []) if str(x).strip()]
    primary_scope = str(extracted.get("primary_scope") or "").strip()
    body_regions = list(extracted.get("body_regions") or [])
    dynamic_intake = bool(evidence_present)
    if dynamic_intake:
        iterative_state = update_hypothesis({"features": evidence_present}, "")

    normalized_complaint = (
        (
            str(complaint.get("id") or "").strip()
            or str(complaint.get("name") or complaint.get("complaint") or "").strip()
        )
        if complaint_is_relevant
        else "general_complaint"
    )

    # hard override from extracted scope to fix branch collisions
    SCOPE_TO_COMPLAINT = {
        "oral_cavity": "oral_cavity",
        "respiratory": "respiratory",
        "urinary": "urinary",
        "gastro": "gastro",
        "neuro": "neuro",
        "cardio": "cardio",
        "allergy_skin": "allergy_skin",
        "fatigue_deficiency": "fatigue_deficiency",
        "pleuritic_chest_dyspnea": "pleuritic_chest_dyspnea",
        "weight_loss_plateau": "weight_loss_plateau",
        "knee": "orthopedics",
        "ankle": "orthopedics",
        "shoulder": "orthopedics",
        "back": "orthopedics",
    }
    if primary_scope in SCOPE_TO_COMPLAINT:
        normalized_complaint = SCOPE_TO_COMPLAINT[primary_scope]

    if any(x in msg for x in ("после сыра", "сыр")) and any(x in msg for x in ("голов", "мигр")):
        normalized_complaint = "headache_after_cheese"
    elif any(x in msg for x in ("после творога", "творог")) and any(x in msg for x in ("голов", "мигр")):
        normalized_complaint = "headache_after_cottage_cheese"
    elif any(x in msg for x in ("пуч", "пука", "газы", "вздут")):
        normalized_complaint = "gas_bloating"
    elif any(x in msg for x in ("жжет", "жжёт", "моч")):
        normalized_complaint = "burning_urination"
    elif primary_scope != "pleuritic_chest_dyspnea" and any(x in msg for x in ("груд", "не хватает воздуха", "одыш")):
        normalized_complaint = "chest_pain_or_dyspnea"

    red_flags_detected = _detect_red_flags(user_message, complaint, sev_ctx)
    graph_red_flags = [
        str((x or {}).get("title") or "").strip()
        for x in (rg_ctx.get("red_flag_matches") or [])
        if isinstance(x, dict) and str((x or {}).get("title") or "").strip()
    ]
    if graph_red_flags:
        red_flags_detected = list(dict.fromkeys([str(x).strip() for x in (red_flags_detected or []) if str(x).strip()] + graph_red_flags))
    iter_red_flags = [str(x).strip() for x in (iterative_state.get("red_flags") or []) if str(x).strip()]
    if iter_red_flags:
        red_flags_detected = list(dict.fromkeys([str(x).strip() for x in (red_flags_detected or []) if str(x).strip()] + iter_red_flags))
    structured_red_flags = detect_structured_red_flags(evidence_present)
    if structured_red_flags:
        red_flags_detected = list(
            dict.fromkeys(
                [str(x).strip() for x in (red_flags_detected or []) if str(x).strip()]
                + [str(x.get("message") or "").strip() for x in structured_red_flags if str(x.get("message") or "").strip()]
            )
        )

    matched_scripts: list[str] = []
    if normalized_complaint:
        matched_scripts.append(normalized_complaint)
    for f in (food_ctx.get("matched_foods") or []):
        fid = str((f or {}).get("id") or "").strip()
        if fid:
            matched_scripts.append("food_trigger_" + fid)
    for p in (food_ctx.get("pattern_matches") or []):
        pid = str((p or {}).get("pattern_id") or "").strip()
        if pid:
            matched_scripts.append(pid)
    for s in (rg_ctx.get("matched_symptoms") or []):
        if isinstance(s, dict):
            name = str(s.get("name") or "").strip()
            if name:
                matched_scripts.append("symptom:" + name.lower())

    labs_signal = _extract_labs_signal(user_message, labs_ctx)
    obvious_food = bool(food_ctx.get("matched_foods")) and any(x in msg for x in ("после", "через"))
    has_lab_pattern = bool(labs_signal) and any(k in labs_signal for k in ("hgb", "urine_leukocytes"))
    rg_food = [x for x in (rg_ctx.get("matched_foods") or []) if isinstance(x, dict)]
    rg_candidates = [x for x in (rg_ctx.get("candidate_conditions") or []) if isinstance(x, dict)]
    iterative_candidates = [x for x in (iterative_state.get("hypotheses") or []) if isinstance(x, dict)]
    rg_labs = [str(x).strip() for x in (rg_ctx.get("lab_suggestions") or []) if str(x).strip()]
    complaint_first_present = bool(complaint and complaint_is_relevant)
    food_present = bool(obvious_food or food_ctx.get("possible_conditions") or rg_food)
    candidate_present = bool(rg_candidates or iterative_candidates)
    labs_present = bool(has_lab_pattern or rg_labs)

    # Required priority:
    # red flags -> complaint-first -> food triggers -> candidate conditions -> lab suggestions -> short answer
    if red_flags_detected:
        mode = "urgent_mode"
    elif complaint_first_present:
        mode = "obvious_pattern"
    elif food_present:
        mode = "obvious_pattern"
    elif candidate_present:
        mode = "obvious_pattern"
    elif labs_present:
        mode = "complaint_lab_reasoning"
    else:
        mode = "focused_questions_mode"

    causes = [
        str(x).strip()
        for x in (
            (
                complaint.get("likely_causes")
                or complaint.get("top_hypotheses")
                or complaint.get("possible_conditions")
                or []
            )
            if complaint_is_relevant
            else []
        )
        if str(x).strip()
    ]
    if not causes:
        if normalized_complaint in ("gas_bloating",):
            causes = ["пищевая ферментация", "частичная непереносимость лактозы", "функциональный метеоризм"]
        elif normalized_complaint in ("headache_after_cheese", "headache_after_cottage_cheese"):
            causes = ["пищевой триггер головной боли", "чувствительность к биогенным аминам", "мигренозный механизм"]
        elif normalized_complaint == "burning_urination":
            causes = ["инфекция нижних мочевых путей", "уретральное раздражение"]
    if iterative_candidates:
        iter_labels = [str(x.get("name") or x.get("label") or "").strip() for x in iterative_candidates if str(x.get("name") or x.get("label") or "").strip()]
        if iter_labels:
            causes = iter_labels[:4]
    if not causes and rg_candidates:
        causes = [str(x.get("label") or "").strip() for x in rg_candidates[:4] if str(x.get("label") or "").strip()]

    disease_candidates = _match_disease_candidates(user_message, complaint, limit=3)
    differential = [{"label": c, "confidence": max(0.42, 0.82 - i * 0.15)} for i, c in enumerate(causes[:3])]
    if not differential:
        differential = disease_candidates[:3]

    leading_label = differential[0]["label"] if differential else "требуется уточнение данных"
    leading_conf = float(differential[0]["confidence"]) if differential else 0.35

    ask = [
        str(x).strip()
        for x in (
            (
                complaint.get("must_ask_questions")
                or complaint.get("anamnesis_questions")
                or []
            )
            if complaint_is_relevant
            else []
            or rg_ctx.get("adaptive_questions")
            or followup_questions
            or []
        )
        if str(x).strip()
    ][:3]
    if iterative_state.get("followup_questions"):
        ask = [str(x).strip() for x in (iterative_state.get("followup_questions") or []) if str(x).strip()][:4] or ask
    safe_actions = [
        str(x).strip()
        for x in (
            complaint.get("first_line_non_drug_steps")
            or complaint.get("treatment_basic")
            or complaint.get("nutrition_recommendations")
            or complaint.get("nutrition_advice")
            or []
        )
        if str(x).strip()
    ][:4]
    if not safe_actions:
        safe_actions = ["щадящий режим", "питьё", "наблюдение динамики"]
    if iterative_state.get("safe_actions"):
        safe_actions = [str(x).strip() for x in (iterative_state.get("safe_actions") or []) if str(x).strip()][:4] or safe_actions
    if rg_labs and mode in ("obvious_pattern", "complaint_lab_reasoning"):
        safe_actions = safe_actions[:2] + [rg_labs[0]]

    escalate = [
        str(x).strip()
        for x in (
            complaint.get("red_flags_specific")
            or complaint.get("red_flags")
            or _load_shared_rules().get("shared_red_flags")
            or []
        )
        if str(x).strip()
    ][:4]
    if not escalate and iter_red_flags:
        escalate = iter_red_flags[:4]

    # Dynamic clinical interview path:
    # complaint -> hypotheses -> best next question -> re-rank on each turn -> care level.
    all_red_flags_for_care: list[Any] = []
    all_red_flags_for_care.extend(structured_red_flags or [])
    all_red_flags_for_care.extend(red_flags_detected or [])
    all_red_flags_for_care.extend(graph_red_flags or [])
    all_red_flags_for_care.extend(iter_red_flags or [])

    next_questions = select_best_questions(
        known_present=set(evidence_present),
        known_absent=set(evidence_absent),
        asked_question_ids=set(),
        max_n=4,
        complaint_hint=f"{normalized_complaint} {user_message}",
        protocol_questions=ask,
    )
    top_hypotheses: list[dict[str, Any]] = []
    for row in (iterative_state.get("hypotheses") or [])[:5]:
        if not isinstance(row, dict):
            continue
        lbl = str(row.get("name") or row.get("label") or "").strip()
        if not lbl:
            continue
        top_hypotheses.append(
            {
                "id": str(row.get("code") or "").strip(),
                "label_ru": lbl,
                "score": round(float(row.get("confidence") or 0.0), 2),
                "rationale": [f"выявлено: {x}" for x in evidence_present[:3]],
            }
        )
    care_level_detail = decide_care_level(
        top_hypotheses,
        all_red_flags_for_care,
        evidence_present=evidence_present,
        normalized_complaint=normalized_complaint,
        user_message=user_message,
    )
    if primary_scenario_id is not None:
        care_level_detail = override_care_level_by_scenario(
            primary_scenario_id,
            care_level_detail,
            evidence_present=evidence_present,
            user_message=user_message,
        )
    care_level = normalize_runner_care_level(care_level_detail)
    rec_bundle = build_recommendations(care_level_detail, top_hypotheses, iterative_state)
    contradictions = detect_contradictions(evidence_present, evidence_absent)
    if dynamic_intake and next_questions:
        selector_questions = [
            str(x.get("text") or "").strip()
            for x in next_questions
            if str(x.get("text") or "").strip()
        ]

        merged_questions: list[str] = []
        seen_questions: set[str] = set()

        for q in selector_questions + ask:
            s = str(q).strip()
            if not s or s in seen_questions:
                continue
            seen_questions.add(s)
            merged_questions.append(s)

        ask = merged_questions[:4]
    if primary_scenario_id is not None:
        ask = override_questions_by_scenario(primary_scenario_id, ask)
    if dynamic_intake and rec_bundle.get("self_care"):
        safe_actions = [str(x).strip() for x in (rec_bundle.get("self_care") or []) if str(x).strip()][:4] or safe_actions

    if dynamic_intake and all_red_flags_for_care:
        structured_msgs = [
            str(x.get("message") or x.get("title") or "").strip()
            for x in all_red_flags_for_care
            if isinstance(x, dict) and str(x.get("message") or x.get("title") or "").strip()
        ]
        raw_msgs = [str(x).strip() for x in all_red_flags_for_care if not isinstance(x, dict) and str(x).strip()]
        escalate = (structured_msgs + raw_msgs)[:4] or escalate

    if dynamic_intake and care_level_detail == "urgent_clinical_assessment":
        mode = "urgent_mode"
    elif dynamic_intake:
        mode = "focused_questions_mode" if ask else "obvious_pattern"
    if dynamic_intake and top_hypotheses:
        leading_label = str(top_hypotheses[0].get("label_ru") or leading_label).strip()
        leading_conf = float(top_hypotheses[0].get("score") or leading_conf)
        differential = [
            {"label": str(x.get("label_ru") or "").strip(), "confidence": float(x.get("score") or 0.0)}
            for x in top_hypotheses[:4]
            if str(x.get("label_ru") or "").strip()
        ] or differential

    return {
        "normalized_complaint": normalized_complaint,
        "user_message": str(user_message or "").strip(),
        "conversation_context": history_text,
        "matched_scripts": matched_scripts,
        "red_flags_detected": red_flags_detected,
        "reasoning_mode": mode,
        "leading_hypothesis": {
            "label": leading_label,
            "confidence": round(leading_conf, 2),
        },
        "differential_list": differential[:4],
        "must_ask_next": ask,
        "questions": ask,
        "safe_actions_now": safe_actions,
        "when_to_escalate": escalate,
        "top_hypotheses": top_hypotheses,
        "next_questions": next_questions,
        "care_level_detail": care_level_detail,
        "care_level": care_level,
        "body_regions": body_regions,
        "primary_scenario_id": primary_scenario_id,
        "contradictions": contradictions,
        "recommendations": rec_bundle,
        "evidence_present": evidence_present,
        "evidence_absent": evidence_absent,
        "evidence_unknown": extracted.get("evidence_unknown") or [],
        "dynamic_intake_mode": dynamic_intake,
        "iterative_hypothesis_state": iterative_state,
        "priority_flow": [
            "red_flags",
            "complaint_first",
            "food_triggers",
            "candidate_conditions",
            "lab_suggestions",
            "short_answer",
        ],
    }


def render_short_answer_from_reasoning(reasoning_output: dict[str, Any]) -> str:
    ro = reasoning_output if isinstance(reasoning_output, dict) else {}
    if ro.get("dynamic_intake_mode"):
        interpretation = "Понял."
        ev = {str(x).strip().lower() for x in (ro.get("evidence_present") or []) if str(x).strip()}
        if "knee_pain" in ev:
            interpretation = "Понял. По вашему описанию это похоже на клинически значимый сценарий боли в колене."
        elif "ankle_pain" in ev:
            interpretation = "Понял. По вашему описанию это похоже на клинически значимый сценарий боли в голеностопе."
        elif "shoulder_pain" in ev:
            interpretation = "Понял. По вашему описанию это похоже на клинически значимый сценарий боли в плече."
        elif "back_pain" in ev:
            interpretation = "Понял. По вашему описанию это похоже на клинически значимый сценарий боли в спине."
        return compose_dynamic_response(
            {
                "interpretation": interpretation,
                "top_hypotheses": ro.get("top_hypotheses") or [],
                "red_flags": [{"message": x} for x in (ro.get("red_flags_detected") or []) if str(x).strip()],
                "next_questions": ro.get("next_questions") or [],
                "self_care": (ro.get("recommendations") or {}).get("self_care") or ro.get("safe_actions_now") or [],
                "care_level": ro.get("care_level") or "",
                "evidence_present": ro.get("evidence_present") or [],
                "chief_complaint": str(ro.get("normalized_complaint") or "").strip(),
                "user_message": str(ro.get("user_message") or "").strip(),
                "conversation_context": str(ro.get("conversation_context") or "").strip(),
            }
        )
    leading = (ro.get("leading_hypothesis") or {}).get("label") or "требуется уточнение данных"
    reasons = "; ".join([str(x.get("label") or "").strip() for x in (ro.get("differential_list") or [])[:3] if str(x.get("label") or "").strip()])
    ask = "; ".join([str(x).strip() for x in (ro.get("must_ask_next") or [])[:3] if str(x).strip()]) or "уточнить динамику симптомов и триггеры."
    actions = "; ".join([str(x).strip() for x in (ro.get("safe_actions_now") or [])[:3] if str(x).strip()]) or "щадящий режим и наблюдение."
    escalate = "; ".join([str(x).strip() for x in (ro.get("when_to_escalate") or [])[:3] if str(x).strip()]) or "при ухудшении или появлении red flags."
    return (
        "Похоже на: " + str(leading).strip() + "\n"
        "Почему это возможно: " + (reasons or str(leading).strip()) + ".\n"
        "Что уточнить: " + ask + "\n"
        "Что можно сделать сейчас (что попробовать): " + actions + "\n"
        "Когда обратиться к врачу: " + escalate
    ).strip()

