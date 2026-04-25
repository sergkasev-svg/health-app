"""
Тексты для конверсии: спокойно, без давления, честно про ценность.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def build_post_value_upgrade_copy(
    feature_key: str = "physician_report",
    tier: str = "free",
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """После первого полезного результата: предложить углубить (отчёт для врача и т.д.)."""
    copy_map = {
        "physician_report": "Можно открыть подробный отчёт для врача — структурированный и без лишнего.",
        "continuity_summary": "Сравнение анализов в динамике доступно в расширенном плане.",
        "trends": "История показателей и тренды доступны в Plus.",
    }
    message = copy_map.get(feature_key, "Расширенные возможности доступны в плане Plus или Pro.")
    return {"message": message, "cta": "Подробнее", "placement": "after_first_result"}


def build_locked_feature_teaser(
    feature_key: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Тизер при попытке открыть заблокированную фичу."""
    copy_map = {
        "physician_report": "Подробный отчёт для врача доступен в Pro. Краткий вывод вы уже видите выше.",
        "report_export": "Экспорт отчёта доступен в Pro.",
        "advanced_trends": "Сравнение анализов в динамике доступно в Plus.",
    }
    message = copy_map.get(feature_key, "Эта функция доступна в расширенном плане.")
    return {"message": message, "cta": "Подробнее", "placement": "after_locked_feature"}


def build_repeat_usage_upgrade_copy(
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Повторный визит: ценность памяти и continuity."""
    message = "Чтобы сохранять историю и не повторять одни и те же вопросы, можно включить Plus."
    return {"message": message, "cta": "Подробнее", "placement": "followup_return"}


def build_followup_upgrade_copy(
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """После follow-up: продолжение маршрута и отчёт для врача."""
    message = "Можно подготовить отчёт для врача и отслеживать динамику показателей в Plus/Pro."
    return {"message": message, "cta": "Подробнее", "placement": "followup_return"}
