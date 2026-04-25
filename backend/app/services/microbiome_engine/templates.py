"""
Шаблоны ответа пользователю и upsell Microbiome Engine v1.
"""
from __future__ import annotations

from typing import Any

AXIS_LABELS_RU = {
    "gut_muscle": "Мышцы",
    "gut_brain": "Мозг",
    "gut_immune": "Иммунитет",
    "gut_skin": "Кожа",
}

AXIS_EMOJI = {
    "gut_muscle": "💪",
    "gut_brain": "🧠",
    "gut_immune": "🛡",
    "gut_skin": "✨",
}

# Общие рекомендации по микробиому (без обещаний лечения)
DEFAULT_RECOMMENDATIONS = [
    "Клетчатка 25–35 г/сут",
    "Разнообразие овощей (минимум 5 видов в день)",
    "Ферментированные продукты",
    "Снижение сахара и ультрапереработки",
]

DISCLAIMER = "⚠️ Это не диагноз. При выраженных симптомах — обратитесь к врачу."


def build_axis_list_for_display(active_axes: list[str]) -> list[str]:
    """Список осей для блока «обнаружены признаки влияния на [ось]»."""
    return [f"{AXIS_EMOJI.get(ax, '')} {AXIS_LABELS_RU.get(ax, ax)}" for ax in active_axes]


def build_report_body(
    active_axes: list[str],
    risk_level: str,
    recommendations: list[str] | None = None,
) -> str:
    """
    Готовый текст блока «Анализ микробиома и состояния организма».
    """
    recs = recommendations or DEFAULT_RECOMMENDATIONS
    axes_display = ", ".join(build_axis_list_for_display(active_axes)) if active_axes else "состояние организма"
    level_ru = {"low": "низкий", "moderate": "средний", "high": "высокий"}.get(risk_level, "средний")

    lines = [
        "📊 Анализ микробиома и состояния организма",
        "",
        "Обнаружены признаки:",
        f"- возможного влияния кишечника на {axes_display}",
        "",
        "🧠 Важно:",
        "Современные исследования показывают, что кишечный микробиом влияет на:",
        "- энергию и силу",
        "- настроение",
        "- иммунитет",
        "- состояние кожи",
        "",
        "📈 Что это значит:",
        "Ваши симптомы могут частично быть связаны с состоянием микробиома.",
        "",
        "✅ Рекомендации:",
    ]
    for i, r in enumerate(recs, 1):
        lines.append(f"{i}. {r}")
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def get_upsell_hook() -> dict[str, Any]:
    """Блок монетизации: персональный план восстановления микробиома."""
    return {
        "title": "Хотите персональный план восстановления микробиома?",
        "description": "Мы составим: питание, добавки, образ жизни.",
        "cta_text": "Получить план",
        "product": "microbiome_upgrade",
        "price_range": "7-15$",
        "includes": [
            "персональный план",
            "4 оси анализа",
            "приоритетные рекомендации",
        ],
    }
