from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.medical_core_answer_quality import evaluate_answer_quality, merge_quality_into_followup_state


REASK_MAP = {
    "duration": "Я уточню коротко: как давно это началось — часы, дни или недели?",
    "location": "Уточните, пожалуйста, где именно основной дискомфорт сейчас?",
    "character": "Опишите характер симптома: давит, колет, жжет, пульсирует или иначе?",
    "severity": "Оцените выраженность по шкале от 1 до 10.",
    "temperature": "Есть температура сейчас? Если есть, назовите значение.",
    "trigger": "С чем вы связываете начало: нагрузка, еда, стресс, жара, травма?",
    "breath": "Есть одышка или ощущение нехватки воздуха?",
    "bleeding": "Кровотечение сейчас продолжается или уже остановилось?",
    "stool": "Есть изменения стула: диарея, запор, кровь, черный стул?",
    "urination": "Есть боль, жжение или учащение при мочеиспускании?",
    "vomiting": "Есть тошнота или рвота сейчас?",
    "pregnancy": "Есть вероятность беременности или задержка цикла?",
    "neuro": "Есть онемение, слабость в руке/ноге, перекос лица или проблемы с речью?",
}

REPAIR_REPLY = "Не до конца понял ответ. Повторите, пожалуйста, коротко и по вопросу."
URGENT_REPLY = (
    "Сейчас есть признаки возможного опасного состояния. "
    "Рекомендую срочно обратиться за неотложной очной помощью."
)


def evaluate_followup_turn(
    *,
    user_text: str,
    followup_state: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    state = dict(followup_state or {})
    pending_question = state.get("pending_question") or {}
    slot = str(pending_question.get("slot") or "").strip() or "generic"

    quality = evaluate_answer_quality(
        user_text=user_text,
        pending_question=pending_question if isinstance(pending_question, dict) else {},
        followup_state=state,
        previous_user_text=state.get("last_user_text"),
    )
    state = merge_quality_into_followup_state(state, quality)
    state["last_user_text"] = user_text

    result: Dict[str, Any] = {
        "quality_status": quality.status,
        "quality_score": quality.score,
        "followup_state": state,
        "action": "continue",
        "assistant_override_text": None,
    }

    if quality.should_escalate or quality.status == "escalation":
        result["action"] = "urgent"
        result["assistant_override_text"] = URGENT_REPLY
        return result

    if quality.status in {"unknown", "off_target", "contradictory", "partial_off_target", "empty"}:
        result["action"] = "reask"
        result["assistant_override_text"] = REASK_MAP.get(slot) or REPAIR_REPLY
        return result

    if quality.status == "partial_with_new_complaint":
        result["action"] = "accept_and_flag_case_shift"
        return result

    return result

