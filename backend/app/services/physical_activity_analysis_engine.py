"""
PhysicalActivityAnalysisEngine: анализ физической активности и общие рекомендации
(150 мин умеренной / 75 мин интенсивной в неделю; силовые 2–3 раза; растяжка; учёт здоровья).
Рекомендации только общие, не заменяют тренера/ЛФК. Изолированный модуль.
"""
from typing import Any

GUIDELINES = {
    "description": "Рекомендации по физической активности по гайдлайнам ВОЗ и доказательным практикам.",
    "aerobic": [
        "Не менее 150 минут умеренной аэробной нагрузки в неделю или 75 минут интенсивной (или комбинация).",
        "Ходьба, плавание, велосипед, лёгкий бег — базовые варианты.",
    ],
    "strength": [
        "Силовые упражнения 2–3 раза в неделю (с весом тела, тренажёры, резинки).",
    ],
    "flexibility": [
        "Растяжка, йога или пилатес — регулярно, для подвижности и восстановления.",
    ],
    "progression": [
        "Прогрессия нагрузки постепенная; при болезнях суставов или сердечно-сосудистых ограничениях — под контролем специалиста.",
    ],
    "recovery": [
        "Дни отдыха и достаточный сон (7–9 часов) для восстановления; при признаках переутомления (overtraining) — снизить объём.",
    ],
    "practices": [
        "Йога, пилатес, функциональный тренинг, HIIT — по переносимости и целям.",
    ],
}


def get_activity_recommendations(
    context_text: str = "",
    mention_joints_or_heart: bool = False,
) -> dict[str, Any]:
    """
    Возвращает структурированные общие рекомендации по физической активности.
    mention_joints_or_heart: если в контексте есть ограничения (суставы, сердце) — добавляется предупреждение.
    """
    out: dict[str, Any] = {
        "summary": GUIDELINES["description"],
        "aerobic": list(GUIDELINES["aerobic"]),
        "strength": list(GUIDELINES["strength"]),
        "flexibility": list(GUIDELINES["flexibility"]),
        "progression": list(GUIDELINES["progression"]),
        "recovery": list(GUIDELINES["recovery"]),
        "practices": list(GUIDELINES["practices"]),
        "caution": [],
    }
    if mention_joints_or_heart or (context_text and any(k in (context_text or "").lower() for k in ["сустав", "сердце", "давление", "кардио"])):
        out["caution"].append("При заболеваниях суставов или сердечно-сосудистой системы объём и тип нагрузки должен согласовываться с врачом или специалистом ЛФК.")
    return out
