"""
Сборка структурированного отчёта для голосового консьержа:
описание, гипотезы, рекомендации по обследованию, питанию, активности, красные флаги, дисклеймер.
Использует только изолированные модули; не меняет логику run_consultation_turn.
"""
from typing import Any

from app.services.medical_relevance_filter import filter_response_by_relevance
from app.services.nutrition_analysis_engine import get_nutrition_recommendations
from app.services.physical_activity_analysis_engine import get_activity_recommendations
from app.services.response_formatter import format_concierge_response
from app.services.voice_medical_input import extract_symptoms_nutrition_activity_intent
from app.services.complaint_reference import search_complaint_reference
from app.services.reasoning_graph_lookup import build_reasoning_graph_context
from app.reasoning.medical_reasoning_engine import build_medical_reasoning_output
from app.services.medical_core_bridge import build_medical_core_context, merge_structured_with_medical_core
from app.services.medical_core_guidance import apply_medical_core_guidance
from app.services.medical_core_selector import MedicalCoreSelector
from app.services.medical_core_followup_state import prime_followup_state
from app.services.medical_core_followup_gate import decide_followup_turn
from app.services.medical_core_followup_gate_v2 import evaluate_followup_turn
from app.services.medical_core_confidence_gate import run_confidence_gate
from app.services.medical_core_safe_summary_renderer import render_safe_summary_bundle

DISCLAIMER = "Информация носит образовательный характер и не заменяет медицинскую помощь. Обратитесь к врачу для диагностики и лечения."
RED_FLAGS_DEFAULT = [
    "Сильный отёк, нарастающая одышка, боль в груди — незамедлительно к врачу или 103.",
    "Постоянная высокая температура, не снижающаяся жаропонижающими — к врачу.",
    "Сильная боль (голова, живот, грудь), потеря сознания, судороги — срочно 103.",
]
CONFIDENCE_SLOT_QUESTION = {
    "duration": "Как давно это началось: часы, дни или недели?",
    "location": "Где именно сейчас основной дискомфорт?",
    "character": "Какая по характеру боль/симптом: давит, колет, жжет, пульсирует?",
    "severity": "Оцените выраженность по шкале от 1 до 10.",
    "temperature": "Есть температура сейчас? Если есть, укажите значение.",
    "trigger": "С чем вы связываете начало: нагрузка, еда, стресс, жара, травма?",
    "breath": "Есть одышка или ощущение нехватки воздуха?",
    "bleeding": "Есть кровотечение сейчас, и продолжается ли оно?",
    "stool": "Есть изменения стула: диарея, запор, кровь, черный стул?",
    "urination": "Есть боль, жжение или учащение при мочеиспускании?",
    "vomiting": "Есть тошнота или рвота сейчас?",
    "pregnancy": "Есть вероятность беременности или задержка цикла?",
    "neuro": "Есть онемение, слабость, перекос лица или трудности с речью?",
}


def build_structured_response(
    user_message: str,
    chat_response_text: str,
    has_lab_data: bool = False,
) -> dict[str, Any]:
    """
    Формирует структурированный ответ для голосового консьержа.
    - description: симптомы, рацион, активность (кратко из запроса + ответа)
    - hypotheses: потенциальные причины (из ответа или по умолчанию пусто)
    - exam_recommendations: анализы/обследования
    - nutrition_advice: советы по питанию (из движка + контекст)
    - activity_advice: советы по активности (из движка + контекст)
    - red_flags: когда срочно к врачу
    - disclaimer: юридический дисклеймер
    """
    extracted = extract_symptoms_nutrition_activity_intent(user_message or "")
    intent = extracted.get("intent") or "general"
    relevance = filter_response_by_relevance(chat_response_text or "", user_message or "", intent)
    filtered_text = relevance.get("filtered_text") or ""
    if not relevance.get("is_sufficient") and relevance.get("insufficient_message"):
        return format_concierge_response({
            "description": "",
            "hypotheses": [],
            "exam_recommendations": [],
            "nutrition_advice": [],
            "activity_advice": [],
            "red_flags": RED_FLAGS_DEFAULT,
            "disclaimer": DISCLAIMER,
            "insufficient_data": True,
            "insufficient_message": relevance["insufficient_message"],
            "suggested_questions": [],
        })

    # Краткое описание из ответа и намерения
    description_parts = []
    if extracted.get("symptoms"):
        description_parts.append("Жалобы: " + "; ".join(extracted["symptoms"][:3]))
    if extracted.get("nutrition_mentions"):
        description_parts.append("Питание: " + "; ".join(extracted["nutrition_mentions"][:2]))
    if extracted.get("activity_mentions"):
        description_parts.append("Активность: " + "; ".join(extracted["activity_mentions"][:2]))
    if filtered_text:
        description_parts.append(filtered_text[:800])
    description = "\n\n".join(description_parts) if description_parts else filtered_text[:500]

    complaint_hits = search_complaint_reference(user_message or "", top_k=1)
    complaint_protocol = complaint_hits[0] if complaint_hits else {}
    reasoning_graph_context = build_reasoning_graph_context(user_message or "", "")
    reasoning = build_medical_reasoning_output(
        user_message=user_message or "",
        complaint_protocol=complaint_protocol,
        food_trigger_context={},
        lab_context={},
        symptom_severity_context={},
        followup_questions=[],
        reasoning_graph_context=reasoning_graph_context,
    )

    hypotheses = []
    leading = (reasoning.get("leading_hypothesis") or {}).get("label")
    if str(leading or "").strip():
        hypotheses.append(str(leading).strip())
    for item in (reasoning.get("differential_list") or []):
        if isinstance(item, dict) and item.get("label"):
            lbl = str(item.get("label") or "").strip()
            if lbl and lbl not in hypotheses:
                hypotheses.append(lbl)
    if not hypotheses and filtered_text:
        hypotheses = [filtered_text[:400]]

    exam_recommendations = [str(x).strip() for x in (reasoning.get("must_ask_next") or []) if str(x).strip()]
    if not exam_recommendations:
        for line in (filtered_text or "").split("\n"):
            line = line.strip()
            if any(k in line.lower() for k in ["анализ", "оак", "сдать", "обследован", "узи", "экг", "ферритин", "ттг", "витамин d"]):
                exam_recommendations.append(line[:250])
    exam_recommendations = exam_recommendations[:10] if exam_recommendations else ["По назначению врача после очного осмотра."]

    # Питание и активность из движков
    nutrition_rec = get_nutrition_recommendations(filtered_text, include_deficit_hints=True)
    nutrition_advice = (
        (nutrition_rec.get("increase") or [])
        + (nutrition_rec.get("balance") or [])
        + (nutrition_rec.get("deficit_hints") or [])
    )[:8]
    activity_rec = get_activity_recommendations(
        filtered_text,
        mention_joints_or_heart=any(k in (filtered_text or "").lower() for k in ["сустав", "сердце", "давление"]),
    )
    activity_advice = (
        (activity_rec.get("aerobic") or [])
        + (activity_rec.get("strength") or [])
        + (activity_rec.get("flexibility") or [])
        + (activity_rec.get("recovery") or [])
    )[:8]

    payload = format_concierge_response({
        "description": description,
        "hypotheses": hypotheses[:5],
        "exam_recommendations": exam_recommendations[:10],
        "nutrition_advice": nutrition_advice,
        "activity_advice": activity_advice,
        "red_flags": RED_FLAGS_DEFAULT,
        "disclaimer": DISCLAIMER,
        "reasoning_mode": reasoning.get("reasoning_mode"),
        "leading_hypothesis": reasoning.get("leading_hypothesis"),
        "insufficient_data": False,
        "insufficient_message": None,
        "suggested_questions": [],
    })

    # Enrich voice-structured output with medical_core if overlay is available.
    core_ctx = build_medical_core_context(user_message or "")
    core_overlay = merge_structured_with_medical_core({}, core_ctx).get("medical_core") or {}
    if core_overlay:
        payload["medical_core"] = core_overlay

    core_summary = core_ctx.get("safe_summary") or {}
    if core_summary.get("tests"):
        payload["exam_recommendations"] = list(
            dict.fromkeys(list(payload.get("exam_recommendations") or []) + list(core_summary.get("tests") or []))
        )[:10]
    if core_summary.get("nutrition"):
        payload["nutrition_advice"] = list(
            dict.fromkeys(list(payload.get("nutrition_advice") or []) + list(core_summary.get("nutrition") or []))
        )[:8]
    if core_summary.get("activity"):
        payload["activity_advice"] = list(
            dict.fromkeys(list(payload.get("activity_advice") or []) + list(core_summary.get("activity") or []))
        )[:8]
    if core_summary.get("red_flags"):
        payload["red_flags"] = list(
            dict.fromkeys(list(payload.get("red_flags") or []) + list(core_summary.get("red_flags") or []))
        )[:8]

    for item in (core_ctx.get("candidate_diseases") or [])[:3]:
        name = str(item.get("name") or item.get("label") or "").strip()
        if name and name not in payload.get("hypotheses", []):
            payload.setdefault("hypotheses", []).append(name)
    payload["hypotheses"] = payload.get("hypotheses", [])[:5]

    selector_payload: dict[str, Any] = {}
    try:
        selector = MedicalCoreSelector()
        if selector.available():
            selector_result = selector.select(
                user_message=user_message or "",
                symptom_context={
                    "symptoms": list(extracted.get("symptoms") or []),
                    "body_location": "",
                    "symptom_summary": "; ".join(list(extracted.get("symptoms") or [])[:3]),
                },
                profile={},
                existing_state={},
                limit=5,
            )
            if selector_result and selector_result.matched:
                selector_payload = selector_result.to_dict()
    except Exception:
        selector_payload = {}

    if selector_payload.get("matched"):
        payload["medical_core_selector"] = selector_payload
        if not payload.get("specialist_route") and selector_payload.get("specialist"):
            payload["specialist_route"] = selector_payload.get("specialist")
        if not payload.get("follow_up_questions") and selector_payload.get("best_question"):
            payload["follow_up_questions"] = [str(selector_payload.get("best_question")).strip()]
        if not payload.get("exam_recommendations") and selector_payload.get("tests"):
            payload["exam_recommendations"] = list(selector_payload.get("tests") or [])[:10]

    # Follow-up state machine (voice-safe one-question gating).
    try:
        followup_state = prime_followup_state(
            {},
            selector_payload=selector_payload,
            triage_level=str(selector_payload.get("triage_level") or ""),
            triage_target=str(selector_payload.get("triage_target") or ""),
            specialist=str(selector_payload.get("specialist") or ""),
        )
        candidate_questions = [str(q).strip() for q in (payload.get("follow_up_questions") or []) if str(q).strip()][:3]
        if selector_payload.get("best_question"):
            bq = str(selector_payload.get("best_question") or "").strip()
            if bq and bq not in candidate_questions:
                candidate_questions.insert(0, bq)
        gate_v2 = evaluate_followup_turn(
            user_text=user_message or "",
            followup_state=followup_state.to_dict() if hasattr(followup_state, "to_dict") else {},
        )
        gate_action = str(gate_v2.get("action") or "").strip().lower()
        if gate_action in {"reask", "urgent"}:
            payload["medical_core_followup"] = {
                "answer_quality": {
                    "status": gate_v2.get("quality_status"),
                    "score": gate_v2.get("quality_score"),
                },
                "quality_gate_action": gate_action,
                "action": gate_action,
                "question": str(gate_v2.get("assistant_override_text") or "").strip(),
                "followup_state": gate_v2.get("followup_state") or {},
            }
            if gate_action == "reask" and str(gate_v2.get("assistant_override_text") or "").strip():
                payload["follow_up_questions"] = [str(gate_v2.get("assistant_override_text")).strip()]
            if gate_action == "urgent":
                payload["severity"] = "RED"
                payload["red_flags_present"] = True
                payload["follow_up_questions"] = []
        else:
            followup_decision = decide_followup_turn(
                user_message=user_message or "",
                followup_state=followup_state,
                candidate_questions=candidate_questions,
                turn_id="voice",
                question_source="voice_structured",
                selector_payload=selector_payload,
                red_flags_present=False,
                severity="YELLOW",
            )
            payload["medical_core_followup"] = {
                "answer_quality": {
                    "status": gate_v2.get("quality_status"),
                    "score": gate_v2.get("quality_score"),
                },
                "quality_gate_action": gate_action or "continue",
                **followup_decision.to_dict(),
            }
            if followup_decision.action in {"ask", "reask"} and str(followup_decision.question or "").strip():
                payload["follow_up_questions"] = [str(followup_decision.question).strip()]
            elif followup_decision.action == "finalize":
                payload["follow_up_questions"] = []
            if gate_action == "accept_and_flag_case_shift":
                payload["case_shift_candidate"] = True

        complaint_entry = core_ctx.get("complaint_entry") if isinstance(core_ctx, dict) else {}
        confidence_input_state = {
            "selector_complaint": str(selector_payload.get("entry_id") or selector_payload.get("entry_name") or ""),
            "complaint_key": str(selector_payload.get("complaint_key") or ""),
            "current_branch": str(selector_payload.get("entry_name") or ""),
            "domain": str((complaint_entry or {}).get("domain") or "").strip().lower(),
            "category": str((complaint_entry or {}).get("category") or "").strip(),
            "triage_level": str(payload.get("severity") or "YELLOW").strip().lower(),
            "urgent": str(payload.get("severity") or "").strip().upper() == "RED",
        }
        confidence_gate = run_confidence_gate(
            orchestrator_state=confidence_input_state,
            followup_state=dict((payload.get("medical_core_followup") or {}).get("followup_state") or {}),
        )
        payload["confidence_gate"] = {
            "confidence": confidence_gate.get("confidence"),
            "should_stop": bool(confidence_gate.get("should_stop")),
            "should_ask_one_more": bool(confidence_gate.get("should_ask_one_more")),
            "next_best_slot": confidence_gate.get("next_best_slot"),
            "reasons": list(confidence_gate.get("reasons") or []),
            "assistant_hint": confidence_gate.get("assistant_hint"),
        }
        payload["followup_ready_for_summary"] = bool((confidence_gate.get("orchestrator_state") or {}).get("followup_ready_for_summary"))
        if payload["confidence_gate"].get("should_stop"):
            payload["follow_up_questions"] = []
            try:
                safe_bundle = render_safe_summary_bundle(
                    user_message=user_message or "",
                    top_hypotheses=list(payload.get("hypotheses") or []),
                    structured_payload=payload,
                    guidance_context=core_ctx,
                    triage_data={
                        "triage": "urgent" if str(payload.get("severity") or "").upper() == "RED" else "routine",
                        "reason": "",
                    },
                    followup_state=dict((payload.get("medical_core_followup") or {}).get("followup_state") or {}),
                )
                payload["patient_summary"] = str(safe_bundle.get("patient_summary") or payload.get("patient_summary") or "").strip()
                payload["patient_facing_response"] = str(
                    safe_bundle.get("patient_facing_response") or payload.get("patient_facing_response") or ""
                ).strip()
                payload["care_plan_today"] = list(safe_bundle.get("care_plan_today") or payload.get("care_plan_today") or [])[:8]
                payload["when_urgent"] = list(safe_bundle.get("when_urgent") or payload.get("when_urgent") or [])[:8]
                payload["safe_summary_renderer"] = dict(safe_bundle.get("safe_summary_renderer") or {})
                payload["treatment_plan"] = dict(safe_bundle.get("treatment_plan") or payload.get("treatment_plan") or {})
            except Exception:
                pass
        elif payload["confidence_gate"].get("should_ask_one_more") and not payload.get("follow_up_questions"):
            slot = str(payload["confidence_gate"].get("next_best_slot") or "").strip().lower()
            maybe_q = CONFIDENCE_SLOT_QUESTION.get(slot)
            if maybe_q:
                payload["follow_up_questions"] = [maybe_q]

        if isinstance(payload.get("medical_core_followup"), dict):
            payload["medical_core_followup"]["confidence_gate"] = dict(payload.get("confidence_gate") or {})
    except Exception:
        pass

    payload = apply_medical_core_guidance(payload, core_ctx, user_message=user_message or "")
    return payload
