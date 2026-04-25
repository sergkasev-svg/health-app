"""
Шаблоны AI-ответов по типу анализа.
Жёсткая изоляция: organic acids → только метаболика, без инфекций/аллергий.
"""
from __future__ import annotations

from typing import Any, Dict, List


def build_organic_acids_response(data: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Шаблон ответа для organic acids.
    Без инфекций, урологии, аллергий, пищевых триггеров.
    """
    data = data or {}
    key_findings = data.get("key_findings") or [
        "Повышена малоновая кислота",
        "Изменения по триптофановому пути",
        "Возможные признаки нарушения энергетического обмена",
    ]
    interpretation = data.get("interpretation") or [
        "Профиль может отражать особенности метаболизма",
        "Без клинического контекста диагноз не устанавливается",
    ]
    what_to_check = data.get("what_to_check") or [
        "консультация врача",
        "оценка питания и витаминов группы B",
        "повторный анализ при необходимости",
    ]

    return {
        "summary": "Выявлены отклонения по органическим кислотам, требуется клиническая интерпретация",
        "key_findings": key_findings[:5],
        "interpretation": interpretation[:5],
        "what_to_check": what_to_check[:5],
        "danger": None,
        "lab_type": "organic_acids",
    }
