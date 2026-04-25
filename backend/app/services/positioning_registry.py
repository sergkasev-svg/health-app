"""
Реестр позиционирования: value propositions по сегментам.
Safety: не заменяем врача; продаём понятную ценность — разбор анализов, отчёты, continuity.
"""
from __future__ import annotations

from app.services.gtm_models import AudienceSegment, ValueProp


def get_audience_segments() -> list[AudienceSegment]:
    return [
        AudienceSegment(
            segment_id="b2c_general",
            name="B2C: обычные пользователи",
            description="Люди, которые хотят понять анализы и что делать дальше.",
            pains=[
                "не понимают анализы",
                "боятся пропустить важное",
                "хотят простой язык",
                "не знают, что делать дальше",
            ],
            desired_outcomes=[
                "понятный разбор простым языком",
                "короткий план действий",
                "понимание, когда срочно обращаться",
                "отчёт, который можно показать врачу",
            ],
            key_features=[
                "lab_interpretation_basic",
                "care_plan_short",
                "emergency_triage",
                "user_report_structured",
            ],
        ),
        AudienceSegment(
            segment_id="engaged_health",
            name="Вовлечённые пользователи здоровья",
            description="Отслеживают динамику, хотят continuity и follow-up.",
            pains=[
                "отслеживают динамику",
                "хотят continuity",
                "хотят follow-up без повторения одного и того же",
                "хотят более глубокую аналитику",
            ],
            desired_outcomes=[
                "память о предыдущих данных",
                "динамика показателей",
                "повторные разборы",
                "расширенные отчёты",
            ],
            key_features=[
                "continuity_summary",
                "trends_basic",
                "followup_support",
                "memory_long",
            ],
        ),
        AudienceSegment(
            segment_id="family_caregivers",
            name="Семейные заботящиеся",
            description="Следят за детьми или родителями, данные разбросаны.",
            pains=[
                "надо следить за детьми/родителями",
                "данные разбросаны",
                "непонятно, что срочно, а что нет",
            ],
            desired_outcomes=[
                "отдельные профили",
                "follow-up",
                "doctor-ready summaries",
                "семейный сценарий сопровождения",
            ],
            key_features=[
                "family_multi_profile",
                "family_shared_reports",
                "continuity_summary",
            ],
        ),
        AudienceSegment(
            segment_id="clinics_b2b",
            name="Клиники / диагностика / B2B",
            description="Нужны быстрые summaries, стандартизация, branded report.",
            pains=[
                "нужно быстро готовить понятные summaries",
                "нужна стандартизация первичного разбора",
                "нужен branded report / workflow",
            ],
            desired_outcomes=[
                "physician-ready structured report",
                "branded outputs",
                "API/ops layer",
                "quality monitoring",
            ],
            key_features=[
                "clinic_physician_mode",
                "clinic_branded_reports",
                "clinic_dashboard_exports",
                "clinic_api_webhook",
            ],
        ),
    ]


def get_value_propositions() -> list[ValueProp]:
    return [
        ValueProp(
            id="vp_b2c_core",
            audience="b2c_general",
            title="Понятный разбор анализов простым языком",
            description="Получите краткий разбор результатов и план действий. Не заменяем врача — помогаем подготовиться к консультации.",
            proof_points=[
                "Краткий план действий",
                "Понимание, когда срочно обращаться",
                "Отчёт, который можно показать врачу",
            ],
            priority=1,
        ),
        ValueProp(
            id="vp_engaged_continuity",
            audience="engaged_health",
            title="Динамика и память о ваших данных",
            description="Сравнение анализов во времени, follow-up без повторения. Расширенные отчёты в Plus/Pro.",
            proof_points=[
                "Память о предыдущих анализах",
                "Тренды показателей",
                "Повторные разборы",
            ],
            priority=2,
        ),
        ValueProp(
            id="vp_family",
            audience="family_caregivers",
            title="Несколько профилей и doctor-ready сводки",
            description="Отдельные профили для близких, сводки для врача, семейное сопровождение.",
            proof_points=[
                "Отдельные профили",
                "Doctor-ready summaries",
                "Семейный сценарий",
            ],
            priority=3,
        ),
        ValueProp(
            id="vp_b2b",
            audience="clinics_b2b",
            title="Структурированный отчёт для врача и branded output",
            description="Physician-ready отчёт, брендированные выводы, API и мониторинг качества.",
            proof_points=[
                "Structured physician report",
                "Branded outputs",
                "API / quality dashboard",
            ],
            priority=4,
        ),
    ]
