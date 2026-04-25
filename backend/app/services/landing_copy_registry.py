"""
Launch-ready копии для лендинга: hero, how it works, trust, use cases, CTA.
Без обещаний «заменим врача»; акцент на понимание данных и подготовку к консультации.
"""
from __future__ import annotations

from typing import Any, Dict, List


def get_hero_section(segment: str | None = None) -> Dict[str, Any]:
    return {
        "headline": "Понятный разбор анализов и план действий",
        "subheadline": "Загрузите результаты или опишите симптомы — получите краткий разбор простым языком и рекомендации. Не заменяем врача: помогаем подготовиться к консультации.",
        "primary_cta": "Начать бесплатно",
        "secondary_cta": "Как это работает",
    }


def get_how_it_works() -> List[Dict[str, str]]:
    return [
        {"step": 1, "title": "Опишите симптомы или загрузите анализы", "description": "Текстом или файлом — PDF, фото."},
        {"step": 2, "title": "Получите понятный разбор", "description": "Краткий вывод простым языком и план действий."},
        {"step": 3, "title": "Сохраните историю и покажите отчёт врачу", "description": "Удобно для повторных визитов и консультаций."},
    ]


def get_trust_section() -> Dict[str, Any]:
    return {
        "title": "Безопасность и доверие",
        "points": [
            "Сервис не заменяет врача и не ставит диагноз.",
            "Помогаем понять данные анализов и заметить тревожные признаки.",
            "Помогаем подготовиться к консультации и сформировать вопросы.",
            "При срочных симптомах всегда рекомендуем обращение за помощью.",
        ],
    }


def get_use_cases() -> List[Dict[str, str]]:
    return [
        {"id": "oak", "title": "Общий анализ крови", "description": "Разбор ОАК простым языком, план действий."},
        {"id": "thyroid", "title": "Гормоны щитовидной железы", "description": "TSH, T4 и др. — краткая интерпретация."},
        {"id": "repeat", "title": "Повторные анализы в динамике", "description": "Сравнение с прошлыми результатами (Plus/Pro)."},
        {"id": "family", "title": "Семейное использование", "description": "Несколько профилей (тариф Семья)."},
        {"id": "physician", "title": "Отчёт для врача", "description": "Структурированный physician-ready summary (Pro)."},
    ]


def get_cta_sections() -> Dict[str, Dict[str, str]]:
    return {
        "start_free": {"title": "Начать бесплатно", "description": "Первый разбор и план действий без оплаты.", "cta": "Начать"},
        "upload_labs": {"title": "Загрузить анализы", "description": "PDF или фото — получите разбор.", "cta": "Загрузить"},
        "open_detailed_report": {"title": "Подробный отчёт для врача", "description": "Доступен в тарифе Про.", "cta": "Подробнее"},
        "continue_followup": {"title": "Продолжить наблюдение", "description": "Динамика и follow-up в Plus.", "cta": "Подробнее"},
    }


def get_landing_copy_blocks(segment: str | None = None) -> Dict[str, Any]:
    return {
        "hero": get_hero_section(segment),
        "how_it_works": get_how_it_works(),
        "trust": get_trust_section(),
        "use_cases": get_use_cases(),
        "cta_sections": get_cta_sections(),
    }
