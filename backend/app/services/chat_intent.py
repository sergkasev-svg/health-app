"""Определение намерения пользователя в чате (симптом, вопрос, другое)."""
import re


def detect_intent(message: str) -> str:
    """Возвращает 'symptom' если похоже на описание симптома, иначе 'general'."""
    if not message or not message.strip():
        return "general"
    msg = message.strip().lower()
    symptom_words = (
        "болит",
        "боль",
        "температура",
        "тошнота",
        "голова",
        "живот",
        "кашель",
        "насморк",
        "слабость",
        "симптом",
        "ощущаю",
        "чувствую",
        "геморрой",
        "гемор",
        "прямая кишка",
        "прямой кишки",
        "анус",
        "анальный",
        "кровь после стула",
        "дефекация",
    )
    if any(w in msg for w in symptom_words):
        return "symptom"
    return "general"
