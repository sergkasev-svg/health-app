"""
Тексты онбординга: intro, empty state, upload prompt, first value, follow-up, return user, physician teaser.
Тон: спокойный, полезный.
"""
from __future__ import annotations

from typing import Any, Dict


def get_intro_screen() -> Dict[str, str]:
    return {
        "title": "Добро пожаловать",
        "body": "Здесь можно описать симптомы или загрузить результаты анализов и получить понятный разбор простым языком. Сервис не заменяет врача — помогает подготовиться к консультации.",
        "cta": "Понятно",
    }


def get_empty_state() -> Dict[str, str]:
    return {
        "title": "С чего начать",
        "description": "Опишите, что вас беспокоит, простыми словами. Или загрузите результаты анализов, если они уже есть.",
        "symptom_hint": "Опишите, что вас беспокоит, простыми словами.",
        "upload_hint": "Или загрузите результаты анализов, если они уже есть.",
    }


def get_upload_prompt() -> Dict[str, str]:
    return {
        "title": "Загрузите анализы",
        "description": "Поддерживаются PDF и изображения. Мы извлечём данные и подготовим разбор.",
    }


def get_symptom_entry_prompt() -> Dict[str, str]:
    return {
        "title": "Опишите симптомы",
        "description": "Кратко опишите, что беспокоит и как давно. Это поможет точнее интерпретировать анализы.",
    }


def get_first_value_reinforcement() -> Dict[str, str]:
    return {
        "title": "Готово",
        "description": "Вы получили первый разбор. Сохраните отчёт или покажите его врачу при необходимости.",
    }


def get_followup_invitation() -> Dict[str, str]:
    return {
        "title": "Есть новые данные",
        "description": "Теперь есть новые данные — можно уточнить вывод и план действий.",
        "cta": "Обновить разбор",
    }


def get_return_user_message() -> Dict[str, str]:
    return {
        "title": "С возвращением",
        "description": "Мы помним предыдущие данные. Можете загрузить новые анализы или задать уточняющий вопрос.",
    }


def get_physician_report_teaser() -> Dict[str, str]:
    return {
        "title": "Отчёт для врача",
        "description": "Подробный структурированный отчёт для врача доступен в тарифе Про.",
        "cta": "Подробнее",
    }


def get_premium_continuity_teaser() -> Dict[str, str]:
    return {
        "title": "Динамика и история",
        "description": "Чтобы не повторять одни и те же вопросы и видеть историю изменений, можно включить расширенный план (Plus).",
        "cta": "Подробнее",
    }


def get_onboarding_copy_blocks(context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    ctx = context or {}
    return {
        "intro": get_intro_screen(),
        "empty_state": get_empty_state(),
        "upload_prompt": get_upload_prompt(),
        "symptom_entry": get_symptom_entry_prompt(),
        "first_value_reinforcement": get_first_value_reinforcement(),
        "followup_invitation": get_followup_invitation(),
        "return_user": get_return_user_message(),
        "physician_report_teaser": get_physician_report_teaser(),
        "premium_continuity_teaser": get_premium_continuity_teaser(),
    }
