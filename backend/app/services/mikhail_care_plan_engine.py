"""
Care Plan Engine: строит пошаговый план действий по state и pathway.
Безопасные рекомендации: наблюдение, анализы, визит к врачу. Без рецептурных назначений.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.care_plan_models import (
    CareAction,
    CarePlan,
    FollowUpCheckpoint,
    MonitoringTarget,
)
from app.services.care_pathway_registry import match_pathway

MAX_ACTIONS = 5
MAX_MONITORING = 4
MAX_CHECKPOINTS = 4


def build_care_plan_message(care_plan: CarePlan) -> str:
    """
    Компактное пользовательское сообщение по плану. До ~1000 символов.
    """
    if not care_plan:
        return ""
    if care_plan.emergency_override:
        parts = [care_plan.summary]
        for a in care_plan.actions[:3]:
            parts.append(f"• {a.title}")
        return "\n".join(parts).strip()[:600]

    parts = ["План действий"]
    for a in care_plan.actions[:MAX_ACTIONS]:
        parts.append(f"• {a.title}" + (f" — {a.description}" if a.description and len(a.description) < 80 else ""))
    if care_plan.monitoring:
        parts.append("")
        parts.append("Что отслеживать")
        for m in care_plan.monitoring[:MAX_MONITORING]:
            parts.append(f"• {m.name}" + (f" ({m.why_it_matters})" if m.why_it_matters and len(m.why_it_matters) < 60 else ""))
    if care_plan.checkpoints:
        parts.append("")
        parts.append("Когда менять маршрут")
        for c in care_plan.checkpoints[:MAX_CHECKPOINTS]:
            parts.append(f"• {c.trigger} — {c.recommended_step}")
    if care_plan.duration_hint:
        parts.append("")
        parts.append(care_plan.duration_hint)
    if care_plan.next_review:
        parts.append(f"Повторная оценка: {care_plan.next_review}")
    text = "\n".join(parts).strip()
    return text[:1000] if len(text) > 1000 else text


class MikhailCarePlanEngine:
    """
    Строит CarePlan по decision_output, контексту оркестратора и памяти.
    Учитывает pathway (железо, щитовидка, аллергия, инфекция) для уточнения плана.
    """

    def build_plan(
        self,
        decision_output: Any,
        orchestrator_context: Optional[Dict[str, Any]],
        memory: Optional[Any] = None,
    ) -> CarePlan:
        """Главный метод: по state и pathway собрать план."""
        state = (decision_output.state if hasattr(decision_output, "state") else (decision_output or {}).get("state")) or "needs_more_data"
        ctx = orchestrator_context or {}

        if state == "emergency":
            return self._build_emergency_plan(decision_output, ctx)

        matched, pathway_id = match_pathway(decision_output, ctx, memory)
        if pathway_id:
            plan = self._build_pathway_plan(state, pathway_id, decision_output, ctx)
            if plan:
                return self._compress_plan(plan)

        if state == "needs_more_data":
            return self._compress_plan(self._build_needs_more_data_plan(decision_output, ctx))
        if state == "request_labs":
            return self._compress_plan(self._build_request_labs_plan(decision_output, ctx))
        if state == "doctor_soon":
            return self._compress_plan(self._build_doctor_soon_plan(decision_output, ctx))
        if state == "self_care":
            return self._compress_plan(self._build_self_care_plan(decision_output, ctx))
        if state == "probable_diagnosis":
            return self._compress_plan(self._build_probable_diagnosis_plan(decision_output, ctx))

        return self._compress_plan(self._build_needs_more_data_plan(decision_output, ctx))

    def _build_emergency_plan(self, decision_output: Any, context: Dict[str, Any]) -> CarePlan:
        return CarePlan(
            state="emergency",
            summary="Требуется срочная медицинская помощь. Не откладывайте обращение.",
            actions=[
                CareAction("Срочно вызвать 103 или 112 (или обратиться в неотложную помощь)", "", "now", None, "emergency", True),
                CareAction("Не оставаться одному при ухудшении", "", "now", None, "emergency", True),
                CareAction("Подготовить список симптомов и анализов, если есть", "", "soon", None, "emergency", True),
            ],
            monitoring=[],
            checkpoints=[],
            duration_hint=None,
            next_review=None,
            doctor_followup_needed=False,
            emergency_override=True,
            debug={"pathway": "emergency"},
        )

    def _build_needs_more_data_plan(self, decision_output: Any, context: Dict[str, Any]) -> CarePlan:
        questions = getattr(decision_output, "questions", None) or (decision_output or {}).get("questions") or []
        return CarePlan(
            state="needs_more_data",
            summary="Данных пока недостаточно для вывода. Полезно уточнить жалобы и при возможности загрузить анализы.",
            actions=[
                CareAction("Ответить на 2–3 ключевых вопроса", "Уточнение поможет сузить круг причин.", "now", None, "monitoring", True),
                CareAction("Загрузить анализы или обследования, если есть", "", "soon", None, "labs", True),
                CareAction("Сообщить длительность и выраженность симптомов", "", "soon", None, "monitoring", True),
            ],
            monitoring=[
                MonitoringTarget("Ухудшение самочувствия", "Потребуется пересмотр маршрута.", "ежедневно", "Срочно обратиться"),
                MonitoringTarget("Появление красных флагов", "Боль в груди, одышка в покое, обморок и т.п.", "сразу", "Вызвать 103/112"),
            ],
            checkpoints=[
                FollowUpCheckpoint("Если стало хуже", "Срочно обратиться к врачу или вызвать помощь.", "urgent"),
                FollowUpCheckpoint("Если симптомы держатся несколько дней без улучшения", "Записаться на очный приём.", "sooner"),
            ],
            duration_hint=None,
            next_review="После получения ответов на вопросы или загрузки анализов.",
            doctor_followup_needed=False,
            emergency_override=False,
            debug={},
        )

    def _build_request_labs_plan(self, decision_output: Any, context: Dict[str, Any]) -> CarePlan:
        labs = getattr(decision_output, "recommended_labs", None) or (decision_output or {}).get("recommended_labs") or []
        lab_list = ", ".join(labs[:5]) if labs else "рекомендованные анализы"
        return CarePlan(
            state="request_labs",
            summary="Для уточнения вывода полезны анализы. После получения результатов загрузите их в систему.",
            actions=[
                CareAction(f"Сдать анализы: {lab_list}", "По назначению врача или в лаборатории.", "soon", None, "labs", True),
                CareAction("После получения результатов загрузить их в систему", "Повторная оценка по новым данным.", "soon", None, "labs", True),
                CareAction("При ухудшении самочувствия не ждать анализов", "Обратиться к врачу очно.", "now", None, "doctor_visit", True),
            ],
            monitoring=[
                MonitoringTarget("Ключевые симптомы", "Слабость, головокружение, одышка и т.д.", "ежедневно", "Ухудшение — к врачу"),
            ],
            checkpoints=[
                FollowUpCheckpoint("Если анализы готовы", "Загрузить результаты для повторной оценки.", "routine"),
                FollowUpCheckpoint("Если стало хуже до готовности анализов", "Обратиться к врачу или срочно при красных флагах.", "sooner"),
            ],
            duration_hint=None,
            next_review="После загрузки результатов анализов.",
            doctor_followup_needed=False,
            emergency_override=False,
            debug={},
        )

    def _build_doctor_soon_plan(self, decision_output: Any, context: Dict[str, Any]) -> CarePlan:
        return CarePlan(
            state="doctor_soon",
            summary="Требуется очная или плановая консультация врача. До визита соблюдайте безопасные рекомендации.",
            actions=[
                CareAction("Записаться к терапевту или профильному врачу", "", "now", None, "doctor_visit", True),
                CareAction("Подготовить результаты анализов и обследований", "", "soon", None, "monitoring", True),
                CareAction("При необходимости досдать анализы по назначению врача", "", "routine", None, "labs", True),
                CareAction("Соблюдать безопасные рекомендации до визита", "Режим, питание, наблюдение.", "soon", None, "self_care", True),
            ],
            monitoring=[
                MonitoringTarget("Ухудшение симптомов", "Может потребоваться ускорить визит.", "ежедневно", "Ускорить обращение"),
                MonitoringTarget("Новые красные флаги", "Боль в груди, одышка в покое, обморок.", "сразу", "Вызвать 103/112"),
            ],
            checkpoints=[
                FollowUpCheckpoint("Появление красных флагов", "Срочно вызвать 103/112.", "emergency"),
                FollowUpCheckpoint("Усиление симптомов", "Ускорить запись к врачу.", "sooner"),
            ],
            duration_hint=None,
            next_review="После очного визита.",
            doctor_followup_needed=True,
            emergency_override=False,
            debug={},
        )

    def _build_self_care_plan(self, decision_output: Any, context: Dict[str, Any]) -> CarePlan:
        return CarePlan(
            state="self_care",
            summary="Пока допустимо наблюдение и щадящие меры. При ухудшении или появлении красных флагов — обращаться к врачу.",
            actions=[
                CareAction("Щадящий режим", "Отдых, избегать перегрузок.", "now", None, "self_care", True),
                CareAction("Достаточное питьё и питание", "Особенно при температуре или слабости.", "now", None, "lifestyle", True),
                CareAction("Наблюдать симптомы 3–5 дней", "Отслеживать температуру, слабость, одышку.", "soon", "3–5 дней", "monitoring", True),
            ],
            monitoring=[
                MonitoringTarget("Температура", "При росте или длительной лихорадке — к врачу.", "2 раза в день", "Высокая температура с ухудшением"),
                MonitoringTarget("Слабость", "Нарастание — повод обратиться.", "ежедневно", "Усиление слабости"),
                MonitoringTarget("Одышка", "Особенно в покое.", "сразу", "Одышка в покое — срочно"),
                MonitoringTarget("Боль", "Новая или усиливающаяся.", "ежедневно", "Сильная боль — к врачу"),
            ],
            checkpoints=[
                FollowUpCheckpoint("Если за 3–7 дней улучшения нет", "Записаться к врачу.", "sooner"),
                FollowUpCheckpoint("Появление красных флагов", "Вызвать 103/112 или срочно в неотложную помощь.", "emergency"),
            ],
            duration_hint="Наблюдение 3–5 дней.",
            next_review="Через 3–7 дней или при ухудшении.",
            doctor_followup_needed=False,
            emergency_override=False,
            debug={},
        )

    def _build_probable_diagnosis_plan(self, decision_output: Any, context: Dict[str, Any]) -> CarePlan:
        """Формулировки «может соответствовать», «для уточнения», «до визита можно»."""
        return CarePlan(
            state="probable_diagnosis",
            summary="Картина может соответствовать ряду состояний. Для уточнения нужен очный осмотр и при необходимости анализы. До визита — только безопасные меры.",
            actions=[
                CareAction("Записаться к врачу для уточнения", "Окончательный вывод — после осмотра.", "now", None, "doctor_visit", True),
                CareAction("Подготовить описание симптомов и имеющиеся анализы", "", "soon", None, "monitoring", True),
                CareAction("До визита соблюдать щадящий режим", "Не назначать себе лекарства без врача.", "soon", None, "self_care", True),
            ],
            monitoring=[
                MonitoringTarget("Динамика симптомов", "Ухудшение — ускорить визит.", "ежедневно", "Ухудшение"),
                MonitoringTarget("Красные флаги", "Боль в груди, одышка в покое, обморок.", "сразу", "Срочная помощь"),
            ],
            checkpoints=[
                FollowUpCheckpoint("Ухудшение или новые тревожные симптомы", "Обратиться к врачу быстрее.", "sooner"),
                FollowUpCheckpoint("Красные флаги", "Вызвать 103/112.", "emergency"),
            ],
            duration_hint=None,
            next_review="После визита к врачу.",
            doctor_followup_needed=True,
            emergency_override=False,
            debug={},
        )

    def _build_pathway_plan(
        self,
        state: str,
        pathway_id: str,
        decision_output: Any,
        context: Dict[str, Any],
    ) -> Optional[CarePlan]:
        """План по шаблону pathway."""
        if pathway_id == "iron_deficiency_pattern":
            return self._pathway_iron_deficiency(decision_output, context)
        if pathway_id == "thyroid_hypothyroid_pattern":
            return self._pathway_hypothyroid(decision_output, context)
        if pathway_id == "thyroid_thyrotoxicosis_pattern":
            return self._pathway_thyrotoxicosis(decision_output, context)
        if pathway_id == "mild_allergy_pattern":
            return self._pathway_mild_allergy(decision_output, context)
        if pathway_id == "mild_infection_pattern":
            return self._pathway_mild_infection(decision_output, context)
        return None

    def _pathway_iron_deficiency(self, decision_output: Any, context: Dict[str, Any]) -> CarePlan:
        labs = getattr(decision_output, "recommended_labs", None) or []
        if not labs:
            labs = ["ферритин", "сывороточное железо", "ОЖСС"]
        return CarePlan(
            state=getattr(decision_output, "state", None) or "request_labs",
            summary="Картина может соответствовать дефициту железа. Для уточнения полезны анализы. До визита к врачу можно обогатить рацион продуктами с железом.",
            actions=[
                CareAction("Сдать ферритин и сывороточное железо (и ОЖСС при назначении)", "", "soon", None, "labs", True),
                CareAction("Обсудить результаты с врачом", "", "soon", None, "doctor_visit", True),
                CareAction("Добавить в рацион продукты с железом (до визита)", "Мясо, печень, бобовые, гречка — по переносимости.", "routine", None, "lifestyle", True),
            ],
            monitoring=self._build_monitoring_targets("iron_deficiency"),
            checkpoints=[
                FollowUpCheckpoint("Усиление слабости или головокружения", "Обратиться к врачу быстрее.", "sooner"),
                FollowUpCheckpoint("Обморок или одышка в покое", "Срочно вызвать 103/112.", "emergency"),
            ],
            duration_hint=None,
            next_review="После сдачи анализов и консультации врача.",
            doctor_followup_needed=True,
            emergency_override=False,
            debug={"pathway": "iron_deficiency_pattern"},
        )

    def _pathway_hypothyroid(self, decision_output: Any, context: Dict[str, Any]) -> CarePlan:
        return CarePlan(
            state="doctor_soon",
            summary="Изменения гормонов щитовидной железы требуют консультации эндокринолога. Подтвердите TSH и свободный T4, обсудите с врачом.",
            actions=[
                CareAction("Подтвердить TSH и свободный T4 (при необходимости повторить)", "", "soon", None, "labs", True),
                CareAction("Записаться к эндокринологу", "", "now", None, "doctor_visit", True),
                CareAction("Загрузить анализы в систему после получения", "", "routine", None, "labs", True),
            ],
            monitoring=self._build_monitoring_targets("thyroid_hypo"),
            checkpoints=[
                FollowUpCheckpoint("Усиление симптомов (сонливость, отёки, слабость)", "Ускорить визит к врачу.", "sooner"),
            ],
            duration_hint=None,
            next_review="После консультации эндокринолога.",
            doctor_followup_needed=True,
            emergency_override=False,
            debug={"pathway": "thyroid_hypothyroid_pattern"},
        )

    def _pathway_thyrotoxicosis(self, decision_output: Any, context: Dict[str, Any]) -> CarePlan:
        return CarePlan(
            state="doctor_soon",
            summary="Изменения гормонов указывают на возможную гиперфункцию щитовидной железы. Нужна очная консультация врача и контроль гормонов.",
            actions=[
                CareAction("Очная консультация врача (эндокринолог)", "", "now", None, "doctor_visit", True),
                CareAction("Контроль гормонов по назначению врача", "", "soon", None, "labs", True),
            ],
            monitoring=self._build_monitoring_targets("thyroid_hyper"),
            checkpoints=[
                FollowUpCheckpoint("Выраженное сердцебиение, одышка или ухудшение", "Срочно обратиться к врачу.", "urgent"),
            ],
            duration_hint=None,
            next_review="После консультации врача.",
            doctor_followup_needed=True,
            emergency_override=False,
            debug={"pathway": "thyroid_thyrotoxicosis_pattern"},
        )

    def _pathway_mild_allergy(self, decision_output: Any, context: Dict[str, Any]) -> CarePlan:
        return CarePlan(
            state="self_care",
            summary="Возможна лёгкая аллергическая реакция. Имеет смысл вспомнить возможные аллергены и наблюдать динамику. При сохранении симптомов — к врачу.",
            actions=[
                CareAction("Вспомнить возможные аллергены (еда, контакт, лекарства)", "", "soon", None, "monitoring", True),
                CareAction("Наблюдать динамику симптомов", "", "soon", None, "monitoring", True),
                CareAction("При сохранении симптомов обратиться к врачу", "", "routine", None, "doctor_visit", True),
            ],
            monitoring=self._build_monitoring_targets("allergy"),
            checkpoints=[
                FollowUpCheckpoint("Отёк лица или затруднение дыхания", "Срочно вызвать 103/112.", "emergency"),
            ],
            duration_hint=None,
            next_review="При ухудшении или через несколько дней.",
            doctor_followup_needed=False,
            emergency_override=False,
            debug={"pathway": "mild_allergy_pattern"},
        )

    def _pathway_mild_infection(self, decision_output: Any, context: Dict[str, Any]) -> CarePlan:
        return CarePlan(
            state="self_care",
            summary="Картина может соответствовать лёгкой инфекции. Щадящий режим, контроль температуры и достаточная жидкость. При ухудшении — к врачу.",
            actions=[
                CareAction("Щадящий режим", "", "now", None, "self_care", True),
                CareAction("Контроль температуры", "Измерять 2 раза в день.", "soon", None, "monitoring", True),
                CareAction("Достаточное питьё", "", "now", None, "lifestyle", True),
                CareAction("При ухудшении обратиться к врачу", "", "soon", None, "doctor_visit", True),
            ],
            monitoring=self._build_monitoring_targets("infection"),
            checkpoints=[
                FollowUpCheckpoint("Высокая температура с ухудшением", "Обратиться к врачу.", "sooner"),
                FollowUpCheckpoint("Новые красные флаги (одышка, спутанность)", "Срочно к врачу или 103/112.", "urgent"),
            ],
            duration_hint="Наблюдение 3–5 дней.",
            next_review="При ухудшении или через 3–5 дней.",
            doctor_followup_needed=False,
            emergency_override=False,
            debug={"pathway": "mild_infection_pattern"},
        )

    def _build_monitoring_targets(self, pattern: str) -> List[MonitoringTarget]:
        if pattern == "iron_deficiency":
            return [
                MonitoringTarget("Слабость", "Может нарастать при анемии.", "ежедневно", "Усиление — к врачу"),
                MonitoringTarget("Головокружение", "Риск обморока.", "ежедневно", "Обморок — срочно"),
                MonitoringTarget("Одышка при нагрузке", "Ухудшение — к врачу.", "при нагрузке", "Одышка в покое — 103/112"),
            ][:MAX_MONITORING]
        if pattern == "thyroid_hypo":
            return [
                MonitoringTarget("Слабость, сонливость", "Типично при гипотиреозе.", "ежедневно", "Усиление — ускорить визит"),
                MonitoringTarget("Отёки", "Могут нарастать.", "ежедневно", "Выраженные отёки — к врачу"),
                MonitoringTarget("Замедленность, прибавка веса", "Обсудить с эндокринологом.", "еженедельно", "Усиление симптомов"),
            ][:MAX_MONITORING]
        if pattern == "thyroid_hyper":
            return [
                MonitoringTarget("Сердцебиение", "Может требовать коррекции.", "ежедневно", "Выраженное — срочно"),
                MonitoringTarget("Тремор", "Отслеживать динамику.", "ежедневно", "Усиление — к врачу"),
                MonitoringTarget("Одышка, слабость", "Ухудшение — ускорить визит.", "ежедневно", "Резкое ухудшение — срочно"),
            ][:MAX_MONITORING]
        if pattern == "allergy":
            return [
                MonitoringTarget("Сыпь, зуд", "Динамика после устранения аллергена.", "ежедневно", "Распространение — к врачу"),
                MonitoringTarget("Насморк, отёк", "Отёк лица/горла — срочно.", "сразу", "Отёк лица или затруднение дыхания — 103/112"),
            ][:MAX_MONITORING]
        if pattern == "infection":
            return [
                MonitoringTarget("Температура", "Снижение или рост.", "2 раза в день", "Высокая с ухудшением — к врачу"),
                MonitoringTarget("Слабость", "Восстановление или ухудшение.", "ежедневно", "Нарастание — к врачу"),
                MonitoringTarget("Дыхание", "Одышка — тревожный признак.", "сразу", "Одышка — срочно"),
                MonitoringTarget("Обезвоживание", "Сухость во рту, мало мочи.", "ежедневно", "Признаки обезвоживания — к врачу"),
            ][:MAX_MONITORING]
        return []

    def _compress_plan(self, plan: CarePlan) -> CarePlan:
        """Ограничить число actions/monitoring/checkpoints."""
        return CarePlan(
            state=plan.state,
            summary=plan.summary,
            actions=plan.actions[:MAX_ACTIONS],
            monitoring=plan.monitoring[:MAX_MONITORING],
            checkpoints=plan.checkpoints[:MAX_CHECKPOINTS],
            duration_hint=plan.duration_hint,
            next_review=plan.next_review,
            doctor_followup_needed=plan.doctor_followup_needed,
            emergency_override=plan.emergency_override,
            debug=plan.debug,
        )
