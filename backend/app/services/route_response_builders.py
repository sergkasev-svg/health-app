"""
Шаблоны ответов по маршруту (без смешивания доменов).
"""
from __future__ import annotations

from typing import Any


def build_organic_acids_response(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.services.ai_response_templates import build_organic_acids_response as _tpl
    return _tpl(extra or {})


def build_cbc_response(headline: str = "") -> dict[str, Any]:
    return {
        "summary": headline or "Профиль общего анализа крови требует клинической интерпретации",
        "key_findings": [],
        "interpretation": ["Интерпретация в контексте жалоб и очного осмотра."],
        "what_to_check": ["Консультация врача", "При необходимости — контроль показателей"],
        "danger": None,
        "lab_type": "cbc",
    }


def build_thyroid_response(headline: str = "") -> dict[str, Any]:
    return {
        "summary": headline or "Показатели щитовидной железы требуют клинической интерпретации",
        "key_findings": [],
        "interpretation": ["Корреляция с симптомами и пальпацией — задача врача."],
        "what_to_check": ["Консультация эндокринолога или терапевта"],
        "danger": None,
        "lab_type": "thyroid",
    }


def build_urine_response(headline: str = "") -> dict[str, Any]:
    return {
        "summary": headline or "Анализ мочи требует клинической интерпретации",
        "key_findings": [],
        "interpretation": ["Связь с симптомами мочевыводящих путей при необходимости."],
        "what_to_check": ["Очный осмотр", "При дизурии — консультация врача"],
        "danger": None,
        "lab_type": "urine",
    }


def build_lipid_response(headline: str = "") -> dict[str, Any]:
    return {
        "summary": headline or "Липидный профиль требует клинической интерпретации",
        "key_findings": [],
        "interpretation": ["Оценка сердечно-сосудистого риска — индивидуально."],
        "what_to_check": ["Консультация врача", "Обсуждение образа жизни"],
        "danger": None,
        "lab_type": "lipid",
    }


def build_generic_safe_response() -> dict[str, Any]:
    return {
        "summary": "Недостаточно данных для узкой интерпретации",
        "key_findings": [],
        "interpretation": ["Уточните жалобы и контекст; при наличии анализов — загрузите документ."],
        "what_to_check": ["Очная консультация при ухудшении"],
        "danger": None,
        "lab_type": "unknown",
    }
