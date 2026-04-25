"""
Onboarding Engine: шаги, первая ценность, next best action, empty state, return guidance.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.conversion_signals import detect_first_value
from app.services.onboarding_models import OnboardingState, OnboardingStep


DEFAULT_FLOW = [
    OnboardingStep("intro", "Что умеет сервис", "Можно описать симптомы, загрузить анализы и получить понятный вывод или отчёт для врача.", "Начать", "intro", False, False),
    OnboardingStep("quick_entry", "С чего начать", "Опишите, что беспокоит, или загрузите анализы.", None, "symptom_entry", False, False),
    OnboardingStep("profile", "Профиль (необязательно)", "Укажите пол и возраст для более точных рекомендаций.", "Заполнить позже", "profile", False, False),
    OnboardingStep("first_value", "Первый результат", "Получите краткий вывод и план действий.", None, "first_result", False, False),
    OnboardingStep("followup", "Дальше", "Ответьте на уточняющие вопросы или загрузите новые данные.", None, "followup", False, False),
]


class OnboardingEngine:
    """
    Оценка онбординга: шаги, next best action, empty state.
    При emergency — не отвлекать.
    """

    def evaluate(
        self,
        user_input: Dict[str, Any],
        onboarding_state: OnboardingState,
        clinical_output: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Вернуть блок для API: is_new_user, current_step_id, first_value_reached,
        steps, next_best_action, empty_state_guidance.
        """
        state = onboarding_state or OnboardingState()
        out = clinical_output or {}
        is_emergency = (out.get("state") == "emergency") or ((out.get("urgency") or "").lower() == "high")

        if is_emergency:
            return {
                "is_new_user": state.is_new_user,
                "current_step_id": None,
                "first_value_reached": state.first_value_reached,
                "steps": [],
                "next_best_action": {"title": "Следуйте рекомендациям выше", "description": "", "cta": None},
                "empty_state_guidance": None,
                "return_guidance": None,
            }

        first_val = detect_first_value(clinical_output)
        if first_val and not state.first_value_reached:
            state.first_value_reached = True
        steps = self._build_onboarding_cards(state, out, user_input)
        next_action = self._build_next_best_action(state, out, user_input)
        empty_guidance = self._build_empty_state_guidance(state, user_input) if self._is_empty_state(state, user_input) else None
        return_guidance = self._build_return_guidance(state, user_input, out) if (not state.is_new_user and (state.first_upload_done or state.first_value_reached)) else None

        return {
            "is_new_user": state.is_new_user,
            "current_step_id": state.current_step_id or ("intro" if state.is_new_user else "first_value"),
            "first_value_reached": state.first_value_reached,
            "steps": steps,
            "next_best_action": next_action,
            "empty_state_guidance": empty_guidance,
            "return_guidance": return_guidance,
        }

    def _is_empty_state(self, state: OnboardingState, user_input: Dict[str, Any]) -> bool:
        if state.first_value_reached:
            return False
        has_text = bool((user_input.get("user_text") or "").strip())
        has_upload = bool(user_input.get("has_uploaded_files") or user_input.get("documents_count") or user_input.get("lab_rows_count"))
        return not has_text and not has_upload

    def _build_default_flow(self) -> List[OnboardingStep]:
        return list(DEFAULT_FLOW)

    def _build_onboarding_cards(
        self,
        state: OnboardingState,
        clinical_output: Dict[str, Any],
        user_input: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        flow = self._build_default_flow()
        completed = set(state.completed_steps or [])
        cards = []
        for s in flow:
            cards.append({
                "step_id": s.step_id,
                "title": s.title,
                "description": s.description,
                "cta": s.cta,
                "step_type": s.step_type,
                "completed": s.step_id in completed,
            })
        return cards

    def _build_empty_state_guidance(self, state: OnboardingState, user_input: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "title": "С чего начать",
            "description": "Опишите симптомы простыми словами или загрузите анализы.",
            "options": [
                {"label": "Опишите симптомы", "cta": "Опишите, что вас беспокоит"},
                {"label": "Загрузите анализы", "cta": "Загрузить общий анализ крови, биохимию, гормоны или анализ мочи"},
            ],
            "footer": "Если результаты уже есть — можно сразу получить разбор.",
        }

    def _build_next_best_action(
        self,
        state: OnboardingState,
        clinical_output: Dict[str, Any],
        user_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        return build_next_best_action(state, clinical_output, user_input.get("memory"), user_input.get("product_context") or {})

    def _build_return_guidance(
        self,
        state: OnboardingState,
        user_input: Dict[str, Any],
        clinical_output: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if state.is_new_user:
            return None
        if user_input.get("pending_labs_uploaded"):
            return {"title": "Новые данные", "message": "Теперь можно уточнить вывод по новым результатам."}
        if state.first_value_reached and user_input.get("is_returning_user"):
            return {"title": "С возвращением", "message": "Можно сравнить текущие показатели с предыдущими или продолжить с новых данных."}
        return {"title": "Продолжим", "message": "Вы уже отвечали на часть вопросов — можно продолжить с новых данных."}


def build_next_best_action(
    onboarding_state: OnboardingState,
    clinical_output: Dict[str, Any],
    memory: Any,
    product_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Следующее лучшее действие: ввод симптомов/анализов, ответ на вопросы, follow-up, загрузка после сдачи, upgrade.
    """
    state = clinical_output.get("state") or ""
    has_symptoms = bool((clinical_output.get("questions") or []) or (clinical_output.get("recommended_labs") or []))
    has_result = bool(clinical_output.get("care_plan") or clinical_output.get("user_report_structured") or (clinical_output.get("final_user_message") or "").strip())
    gated = (product_context or {}).get("gated_features") or []
    pending_labs = ((clinical_output.get("continuity_summary") or {}).get("pending_labs") or []) or []

    if not onboarding_state.first_value_reached and not has_result:
        return {
            "title": "Опишите симптомы или загрузите анализы",
            "description": "Кратко опишите, что беспокоит, или прикрепите файлы с результатами.",
            "cta": "Опишите или загрузите",
        }
    if has_result and has_symptoms and not pending_labs:
        return {
            "title": "Ответьте на уточняющие вопросы",
            "description": "Или загрузите дополнительные анализы при необходимости.",
            "cta": "Ответить или загрузить",
        }
    if has_result and pending_labs:
        return {
            "title": "После сдачи анализов",
            "description": "Загрузите результаты, когда будут готовы — тогда можно будет уточнить вывод.",
            "cta": "Загрузить результаты",
        }
    if has_result and gated and "physician_report" in gated:
        return {
            "title": "Подробный отчёт для врача",
            "description": "Доступен в плане Pro — структурированный отчёт без лишнего.",
            "cta": "Подробнее",
        }
    if has_result:
        return {
            "title": "Дальше",
            "description": "Можно вернуться с новыми данными или уточняющими ответами.",
            "cta": "Продолжить позже",
        }
    return {
        "title": "Опишите симптомы или загрузите анализы",
        "description": "",
        "cta": "Начать",
    }
