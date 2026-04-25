"""
B2B офферы: clinic pilot, lab partner, employer wellness, white-label/API.
"""
from __future__ import annotations

from typing import Any, Dict, List


def get_b2b_offers() -> List[Dict[str, Any]]:
    return [
        {
            "offer_id": "clinic_pilot",
            "title": "Пилот для клиник",
            "who_it_is_for": "Клиники и диагностические центры",
            "core_value": "Структурированный physician report, стандартизация первичного разбора, экономия времени врача.",
            "rollout_mode": "Pilot, ограниченное число клиник",
            "required_features": ["clinic_physician_mode", "clinic_dashboard_exports"],
            "success_metrics": ["NPS", "time to report", "adoption rate"],
        },
        {
            "offer_id": "lab_partner",
            "title": "Партнёрство с лабораториями",
            "who_it_is_for": "Лаборатории и сети",
            "core_value": "Понятный разбор результатов для пациентов, снижение нагрузки на call-центр, доп. сервис.",
            "rollout_mode": "Pilot с одной/двумя лабораториями",
            "required_features": ["lab_interpretation_basic", "user_report_structured", "report_export"],
            "success_metrics": ["volume", "patient satisfaction", "support ticket reduction"],
        },
        {
            "offer_id": "employer_wellness",
            "title": "Корпоративный пилот (wellness)",
            "who_it_is_for": "HR / wellness программ компаний",
            "core_value": "Доступ сотрудников к разбору анализов и рекомендациям в рамках wellness.",
            "rollout_mode": "Pilot с одним работодателем",
            "required_features": ["lab_interpretation_basic", "care_plan_short", "report_export"],
            "success_metrics": ["activation", "engagement", "retention"],
        },
        {
            "offer_id": "white_label_api",
            "title": "White-label / API пилот",
            "who_it_is_for": "Партнёры с собственной фронтом или продуктом",
            "core_value": "API для разбора анализов и physician report, брендированный вывод.",
            "rollout_mode": "Ограниченный API доступ",
            "required_features": ["clinic_api_webhook", "clinic_branded_reports"],
            "success_metrics": ["API usage", "error rate", "partner NPS"],
        },
    ]


def get_b2b_cta_copy() -> Dict[str, str]:
    return {
        "title": "Для клиник и партнёров",
        "description": "Структурированные отчёты для врача, API и пилотные программы. Напишите нам.",
        "cta": "Связаться",
    }
