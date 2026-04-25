"""
Модуль «Сила и микробиом»: ось кишечник—мышцы (gut_muscle_axis).
Активируется при жалобах на слабость, усталость, снижение силы; возвращает
insight-блок по Roseburia inulinivorans и блок «Анализ силы и метаболизма».
Не является диагнозом или назначением лечения.
"""
from __future__ import annotations

from typing import Any

# Триггеры активации модуля gut_muscle_axis (жалобы)
GUT_MUSCLE_COMPLAINT_TRIGGERS = [
    "слабость",
    "нет сил",
    "усталость",
    "утомляемость",
    "снижение силы",
    "старею",
    "восстановление плохое",
    "мышечная слабость",
    "сил нет",
    "слабость в ногах",
    "слабость в руках",
]

# Рекомендации (доказанные меры + поддержка микробиома как перспектива)
STRENGTH_METABOLISM_RECOMMENDATIONS = [
    "Силовые нагрузки 2–3 раза в неделю",
    "Белок: 1,2–1,6 г/кг массы тела",
    "Поддержка микробиома: инулин/пребиотики, разнообразие клетчатки (перспективное направление, не замена базовым мерам)",
    "При выраженной слабости — обратиться к врачу для оценки возможной саркопении",
]

INSIGHT_GUT_MUSCLE = {
    "type": "insight",
    "title": "Связь кишечника и мышечной силы",
    "content": (
        "Некоторые кишечные бактерии, включая Roseburia inulinivorans, "
        "связаны с более высокой мышечной силой в исследованиях. "
        "Это перспективное направление науки об оси «кишечник — мышцы», "
        "но не диагноз и не готовое лечение."
    ),
    "confidence": "emerging_evidence",
    "axis": "gut_muscle",
}


def _message_matches_triggers(message: str) -> bool:
    if not message or not message.strip():
        return False
    low = message.strip().lower()
    return any(t in low for t in GUT_MUSCLE_COMPLAINT_TRIGGERS)


def _compute_risk_score(
    message: str,
    age: int | None = None,
    low_activity: bool | None = None,
    protein_deficit_hint: bool = False,
) -> int:
    """
    gut_muscle_risk_score = age_factor + inactivity_factor + protein_deficit + fatigue_score.
    Упрощённо: по сообщению считаем fatigue_score; возраст и активность — опционально.
    """
    score = 0
    # fatigue_score по ключевым словам (0–2)
    low = (message or "").strip().lower()
    if any(k in low for k in ("слабость", "усталость", "утомляемость", "нет сил", "сил нет")):
        score += 1
    if any(k in low for k in ("снижение силы", "мышечная слабость", "старею", "восстановление плохое")):
        score += 1
    # age_factor (0–2)
    if age is not None:
        if age >= 65:
            score += 2
        elif age >= 50:
            score += 1
    # inactivity_factor (0–2)
    if low_activity:
        score += 2
    # protein_deficit (0–1) — по подсказке, в реальности из анкеты/анализа
    if protein_deficit_hint:
        score += 1
    return min(score, 10)


def _risk_level_from_score(score: int) -> str:
    if score <= 2:
        return "low"
    if score <= 5:
        return "moderate"
    return "high"


def evaluate_gut_muscle_axis(
    user_message: str,
    age: int | None = None,
    low_activity: bool | None = None,
    protein_deficit_hint: bool = False,
) -> dict[str, Any]:
    """
    Проверяет, нужно ли активировать модуль «Сила и микробиом».
    Возвращает:
    - active: bool
    - axis: "gut_muscle"
    - risk_score: int (0–10)
    - risk_level: "low" | "moderate" | "high"
    - insight_block: dict для вставки в structured.insights
    - strength_metabolism_block: готовый текст блока «Анализ силы и метаболизма»
    - recommendations: список рекомендаций
    """
    active = _message_matches_triggers(user_message or "")
    if not active and age is None and low_activity is None:
        return {
            "active": False,
            "axis": "gut_muscle",
            "risk_score": 0,
            "risk_level": "low",
            "insight_block": None,
            "strength_metabolism_block": None,
            "recommendations": [],
        }

    # Активируем также при возрасте > 50 или низкой активности без явной жалобы
    if not active and (age and age > 50 or low_activity):
        active = True

    risk_score = _compute_risk_score(
        user_message or "",
        age=age,
        low_activity=low_activity,
        protein_deficit_hint=protein_deficit_hint,
    )
    risk_level = _risk_level_from_score(risk_score)

    if not active:
        return {
            "active": False,
            "axis": "gut_muscle",
            "risk_score": risk_score,
            "risk_level": risk_level,
            "insight_block": None,
            "strength_metabolism_block": None,
            "recommendations": [],
        }

    # Форматированный блок для пользователя (как в ТЗ)
    block_lines = [
        "📊 Анализ силы и метаболизма",
        "",
        "Обнаружены признаки:",
        "- возможного снижения мышечной функции",
        "- возрастных изменений мышц (при наличии соответствующих жалоб или возраста)",
        "",
        "🧠 Важно:",
        "Новые исследования показывают связь кишечных бактерий (например, Roseburia inulinivorans) с мышечной силой. Это не диагноз и не лечение, но важный фактор.",
        "",
        "📈 Что это значит для вас:",
        "- микробиом может влиять на силу и восстановление",
        "- это дополнительная точка роста наряду с тренировками и питанием",
        "",
        "✅ Рекомендации:",
    ]
    for i, rec in enumerate(STRENGTH_METABOLISM_RECOMMENDATIONS, 1):
        block_lines.append(f"{i}. {rec}")
    block_lines.append("")
    strength_metabolism_block = "\n".join(block_lines)

    return {
        "active": True,
        "axis": "gut_muscle",
        "risk_score": risk_score,
        "risk_level": risk_level,
        "insight_block": INSIGHT_GUT_MUSCLE,
        "strength_metabolism_block": strength_metabolism_block,
        "recommendations": list(STRENGTH_METABOLISM_RECOMMENDATIONS),
    }
