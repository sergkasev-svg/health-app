"""
Guardrails для микробиомного модуля v1.1: запрещённые формулировки и безопасные замены.
"""
from __future__ import annotations

FORBIDDEN_PATTERNS_RU = [
    "лечит саркопению",
    "лечит депрессию",
    "лечит тревогу",
    "лечит акне",
    "назначить пробиотик как лечение",
    "назначить как терапию",
    "доказанно повышает силу у людей",
    "заменяет врача"
]

REPLACEMENTS_RU = {
    "лечит саркопению": "рассматривается как перспективное исследовательское направление при снижении мышечной функции",
    "лечит депрессию": "не является доказанным лечением депрессии",
    "лечит тревогу": "не является доказанным лечением тревожного расстройства",
    "лечит акне": "не является доказанным самостоятельным лечением акне",
    "доказанно повышает силу у людей": "связана с мышечной силой, но клиническая эффективность у людей пока не доказана",
    "назначить как терапию": "требуются клинические испытания у людей; не является назначением терапии"
}


def sanitize_microbiome_text(text: str) -> str:
    """Подмена запрещённых формулировок на безопасные."""
    out = text or ""
    for bad, safe in REPLACEMENTS_RU.items():
        out = out.replace(bad, safe)
    return out


_AXIS_LINE_TITLE_RU: dict[str, str] = {
    "gut_muscle": "Ось «кишечник — мышцы и сила»",
    "gut_brain": "Ось «кишечник — настроение и сон»",
    "gut_immune": "Ось «кишечник — иммунитет»",
    "gut_skin": "Ось «кишечник — кожа»",
}


def enrich_with_microbiome(payload: dict, response_parts: list[str]) -> list[str]:
    """
    Добавляет блок «Микробиомный модуль» к списку частей ответа и возвращает
    итоговый список (одной строкой после sanitize). Не диагноз.
    """
    from app.services.microbiome_axes_engine import calc_microbiome_axes

    axes = calc_microbiome_axes(payload)
    if not axes:
        return response_parts

    parts = list(response_parts) if response_parts else []
    parts.append("")
    parts.append("Микробиомный модуль:")
    level_ru = {"low": "низкий", "moderate": "умеренный", "high": "высокий"}
    for axis in axes:
        level_label = level_ru.get(axis.level, axis.level)
        axis_title = _AXIS_LINE_TITLE_RU.get(axis.axis, axis.axis)
        parts.append(f"- {axis_title}: риск/значимость — {level_label}")
        for insight in axis.insights:
            parts.append(f"  • {insight}")
        for rec in axis.recommendations[:3]:
            parts.append(f"  • Рекомендация: {rec}")
    final = "\n".join(parts)
    return [sanitize_microbiome_text(final)]
