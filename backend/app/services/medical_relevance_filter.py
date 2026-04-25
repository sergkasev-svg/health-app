"""
MedicalRelevanceFilter: исключение нерелевантной информации и снижение «галлюцинаций».
Ответ только по теме запроса (простуда — инфекция; диета — нутриенты; тренировка — упражнения).
Изолированный модуль.
"""
import re
from typing import Any

from app.services.voice_medical_input import extract_symptoms_nutrition_activity_intent
try:
    from app.branches.zaz_food_branch_integration import FoodBranchRelevanceFilter
except Exception:
    FoodBranchRelevanceFilter = None

# Фразы, которые вырезаем из ответа, если они не соответствуют контексту запроса
_OFF_TOPIC_PATTERNS = [
    (r"кровотечен[ия]?[^\n.]*", "bleeding"),
    (r"при кровотечен[ии][^\n.]*", "bleeding"),
    (r"инфаркт[^\n.]*", "cardiac"),
    (r"инсульт[^\n.]*", "stroke"),
    (r"срочно\s+103[^\n.]*", "emergency_generic"),
]

# Минимальная длина осмысленного ответа (символов)
_MIN_RELEVANT_LENGTH = 30


def filter_response_by_relevance(response_text: str, user_message: str, intent: str) -> dict[str, Any]:
    """
    Проверяет ответ на релевантность запросу. Возвращает:
    - filtered_text: ответ с вырезанными нерелевантными блоками (по контексту intent)
    - is_sufficient: True если ответ содержательный
    - insufficient_message: сообщение «У меня недостаточно данных», если ответ пустой/нерелевантный
    """
    response_text = (response_text or "").strip()
    user_message = (user_message or "").strip()
    intent = intent or "general"

    if not response_text:
        return {
            "filtered_text": "",
            "is_sufficient": False,
            "insufficient_message": "Недостаточно данных. Коротко: что беспокоит, как давно и что пробовали? Либо загрузите анализы во вкладке «Анализы».",
        }

    filtered = response_text
    user_lower = (user_message or "").lower()
    # Удаляем упоминания кровотечений, если пользователь не спрашивал про кровь/травмы/ЖКТ
    if not any(k in user_lower for k in ["кровь", "кровотечен", "травм", "язв", "желудок", "кишечник", "десн"]):
        for pattern, tag in _OFF_TOPIC_PATTERNS:
            if tag == "bleeding":
                filtered = re.sub(pattern, " ", filtered, flags=re.IGNORECASE)
    filtered = re.sub(r"\n\s*\n\s*\n", "\n\n", filtered).strip()

    if len(filtered) < _MIN_RELEVANT_LENGTH:
        return {
            "filtered_text": filtered,
            "is_sufficient": False,
            "insufficient_message": "У меня недостаточно данных для ответа. Уточните, пожалуйста, симптомы или загрузите результаты анализов.",
        }

    return {
        "filtered_text": filtered,
        "is_sufficient": True,
        "insufficient_message": None,
    }


class MedicalRelevanceFilter:
    """Lightweight relevance helper for specialized branches."""

    def __init__(self) -> None:
        self.food_branch_filter = FoodBranchRelevanceFilter() if FoodBranchRelevanceFilter else None

    def score_food_branch_relevance(self, text: str) -> float:
        if not self.food_branch_filter:
            return 0.0
        try:
            return float(self.food_branch_filter.score(text))
        except Exception:
            return 0.0
