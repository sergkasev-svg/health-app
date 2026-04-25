"""
Follow-up engine: обновление плана, следующие вопросы, мониторинг.
Учитывает уже заданные вопросы и загруженные анализы.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.mikhail_memory import FollowUpPlan, MikhailSessionMemory
from app.services.mikhail_decision_engine import DecisionOutput
from app.services.lab_trend_analyzer import get_latest_marker


class MikhailFollowUpEngine:
    """
    Обновляет follow-up план по результатам decision engine и контексту.
    Выдаёт только новые вопросы (не повторяет уже заданные и отвеченные).
    """

    def update_plan(
        self,
        memory: MikhailSessionMemory,
        decision_output: Optional[DecisionOutput],
        orchestrator_context: Optional[Dict[str, Any]],
    ) -> FollowUpPlan:
        """Обновить план: pending_questions, pending_labs, monitoring_targets, next_step."""
        plan = memory.follow_up_plan or FollowUpPlan()
        plan = FollowUpPlan(
            pending_questions=list(plan.pending_questions),
            pending_labs=list(plan.pending_labs),
            monitoring_targets=list(plan.monitoring_targets),
            next_step=plan.next_step,
        )
        state = (decision_output and decision_output.state) or "needs_more_data"
        if state == "emergency":
            plan.pending_questions = []
            plan.pending_labs = []
            plan.next_step = "Срочно обратиться за помощью (103/112)."
            return plan
        if state == "needs_more_data" and decision_output and decision_output.questions:
            plan.pending_questions = list(decision_output.questions)[:3]
        if state == "request_labs" and decision_output and decision_output.recommended_labs:
            for lab in decision_output.recommended_labs[:5]:
                if lab and lab not in plan.pending_labs:
                    plan.pending_labs.append(lab)
            plan.next_step = "Сдать рекомендованные анализы и загрузить результаты."
        if state == "doctor_soon":
            plan.next_step = "Показать результаты врачу / записаться на очный приём."
            topics = (orchestrator_context or {}).get("structured_lab_report") or {}
            topics = (topics.get("hidden_debug") or topics.get("debug") or {}).get("topics") or []
            plan.monitoring_targets = list(set(plan.monitoring_targets + topics))[:10]
        if state == "self_care":
            plan.next_step = "Наблюдать динамику 3–5 дней."
            plan.monitoring_targets = list(set(plan.monitoring_targets + ["температура", "слабость", "симптомы"]))[:10]
        return plan

    def get_next_questions(
        self,
        memory: MikhailSessionMemory,
        decision_output: Optional[DecisionOutput],
    ) -> List[str]:
        """
        Вопросы для пользователя: убрать уже заданные и отвеченные, макс. 3.
        """
        if not decision_output or not decision_output.questions:
            return []
        asked_lower = {(q.question or "").strip().lower() for q in (memory.asked_questions or []) if (q.question or "").strip()}
        answered_lower = {(a.question or "").strip().lower() for a in (memory.asked_questions or []) if (a.question or "").strip() and a.answered}
        out = []
        for q in decision_output.questions[:3]:
            ql = (q or "").strip().lower()
            if not ql:
                continue
            if ql in answered_lower:
                continue
            if ql in asked_lower and ql not in answered_lower:
                if len(out) < 2:
                    out.append(q.strip())
                continue
            out.append(q.strip() if isinstance(q, str) else str(q).strip())
        return out[:3]

    def get_monitoring_summary(self, memory: MikhailSessionMemory) -> Dict[str, Any]:
        """Краткое суммари для continuity: известные симптомы, pending (лабы уже сданные убираем), next_step."""
        plan = memory.follow_up_plan
        known = [s.name for s in (memory.symptoms or []) if s.name][:15]
        pending_labs = list(plan.pending_labs)[:5] if plan else []
        # Убрать из pending_labs те анализы, которые уже есть в memory
        pending_labs = [p for p in pending_labs if get_latest_marker(memory, p) is None]
        return {
            "known_symptoms": known,
            "pending_questions": list(plan.pending_questions)[:5] if plan else [],
            "pending_labs": pending_labs[:5],
            "monitoring_targets": list(plan.monitoring_targets)[:5] if plan else [],
            "next_step": plan.next_step if plan else None,
        }
