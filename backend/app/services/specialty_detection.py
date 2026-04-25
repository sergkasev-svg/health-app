"""
Определение роли специалиста по контексту диалога и данным документов.
ИИ выступает как врач, нутрициолог, эндокринолог и т.д. в зависимости от темы и загруженных данных.
"""
import re
from typing import Tuple


# Ключевые слова и фразы по направлениям (нижний регистр для поиска)
_NUTRITION = [
    "питание", "диета", "еда", "продукт", "нутрициолог", "вес", "похудение", "набор веса",
    "железо", "гемоглобин", "анемия", "дефицит железа", "витамин", "микроэлемент",
    "калори", "белок", "жир", "углевод", "пищеварение", "желудок", "кишечник",
]
_ENDOCRINOLOGY = [
    "гормон", "щитовидная", "тиреоид", "ттг", "кортизол", "инсулин", "глюкоза", "сахар",
    "эндокринолог", "надпочечник", "гипотиреоз", "гипертиреоз", "диабет",
    "мелатонин", "дгэа", "половой гормон", "пролактин",
]
_CARDIOLOGY = [
    "сердце", "давление", "гипертония", "гипотония", "пульс", "кардиолог",
    "давление", "артериальное", "тахикардия", "аритмия", "грудная боль",
]
_NEUROLOGY = [
    "головная боль", "мигрень", "головокружение", "невролог", "нерв", "инсульт",
    "память", "концентрация", "сон", "бессонница", "инсомния",
]
_STRESS_MENTAL = [
    "стресс", "выгорание", "тревога", "паника", "депрессия", "психо", "усталость",
    "утомление", "напряжение", "эмоци",
]
_DOCUMENT_LAB = [
    "анализ", "результат", "документ", "загрузил", "бланк", "лаборатор", "оак", "биохимия",
]


def detect_specialty(
    user_message: str,
    chat_history: list,
    document_context: str = "",
) -> Tuple[str, str]:
    """
    Определяет роль специалиста по сообщению пользователя, истории чата и контексту документов.
    Возвращает (ключ_роли, подпись_для_промпта на русском).
    """
    text = (user_message or "").lower()
    for m in (chat_history or [])[-6:]:
        if m.get("role") == "user":
            text += " " + (m.get("content") or "").lower()
    text += " " + (document_context or "").lower()
    text = re.sub(r"[^\w\sа-яёa-z0-9]", " ", text)

    scores = {
        "nutrition": 0,
        "endocrinology": 0,
        "cardiology": 0,
        "neurology": 0,
        "stress_mental": 0,
    }

    for w in _NUTRITION:
        if w in text:
            scores["nutrition"] += 2
    for w in _ENDOCRINOLOGY:
        if w in text:
            scores["endocrinology"] += 2
    for w in _CARDIOLOGY:
        if w in text:
            scores["cardiology"] += 2
    for w in _NEUROLOGY:
        if w in text:
            scores["neurology"] += 2
    for w in _STRESS_MENTAL:
        if w in text:
            scores["stress_mental"] += 2

    # Контекст документов: выводы по анализам подсказывают специалиста
    if document_context:
        for w in ["железо", "гемоглобин", "анемия", "ферритин", "дефицит"]:
            if w in document_context.lower():
                scores["nutrition"] += 3
        for w in ["кортизол", "ттг", "тиреоид", "гормон", "инсулин", "глюкоза", "мелатонин"]:
            if w in document_context.lower():
                scores["endocrinology"] += 3
        for w in ["давление", "холестерин", "сердце"]:
            if w in document_context.lower():
                scores["cardiology"] += 2

    best = max(scores.items(), key=lambda x: x[1])
    if best[1] == 0:
        return "general", "врач-терапевт (сбор анамнеза и первичная оценка)"

    labels = {
        "nutrition": "нутрициолог / специалист по питанию",
        "endocrinology": "врач-эндокринолог",
        "cardiology": "врач-кардиолог",
        "neurology": "врач-невролог / специалист по сну",
        "stress_mental": "специалист по стрессу и психосоматике",
    }
    return best[0], labels.get(best[0], "врач-терапевт")
