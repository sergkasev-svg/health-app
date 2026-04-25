"""
VoiceMedicalInput: извлечение из текста сообщения симптомов, питания, активности и намерения.
Изолированный модуль. Не меняет существующую логику чата.
"""
import re
from typing import Any


# Ключевые слова по намерениям (нижний регистр)
_INTENT_ILLNESS = [
    "болит", "боль", "температура", "кашель", "горло", "насморк", "тошнота", "рвота",
    "головокружение", "слабость", "усталость", "устал", "устав", "апат", "не хочется",
    "ничего не хочется", "симптом", "диагноз", "лечение", "врач",
    "простуда", "грипп", "аллергия", "давление", "сердце", "живот", "спина", "сустав",
    "кожа", "сыпь", "пятно", "пятна", "зуд", "чешется", "красное",
    "плохо", "самочувствие", "недомогание", "отравлен", "отравился", "тошнит",
    "подташнивает", "стало плохо", "мне плохо", "плохое самочувствие", "жалоб",
    "непереносимость", "гормональный", "подсолнечник", "помочь", "семена",
    "ухудшилось", "семечк", "кишечник", "поплохело", "поплохела",
]
_INTENT_NUTRITION = [
    "питание", "диета", "еда", "ешь", "ем", "рацион", "калории", "белок", "жир", "углевод",
    "витамин", "железо", "дефицит", "нутрициолог", "похудение", "набор веса", "вода", "пить",
]
_INTENT_FITNESS = [
    "шаги", "тренировка", "зал", "бег", "ходьба", "упражнен", "физнагрузк", "активность",
    "спорт", "фитнес", "йога", "растяжка", "кардио", "силов", "переутомлен", "overtraining",
]


def _match_keyword(lower: str, tokens: set[str], keyword: str) -> bool:
    """Match keyword as token or stable stem, not random substring."""
    k = (keyword or "").lower().strip()
    if not k:
        return False
    if k in tokens:
        return True
    # Stem-like keywords are intentionally short and meant as prefixes.
    if len(k) >= 6:
        for t in tokens:
            if t.startswith(k):
                return True
    return False


def extract_symptoms_nutrition_activity_intent(text: str) -> dict[str, Any]:
    """
    Из текста голосового или текстового сообщения извлекает:
    - symptoms: упоминания симптомов (фразы)
    - nutrition_mentions: упоминания питания
    - activity_mentions: упоминания активности
    - intent: "illness" | "nutrition" | "fitness" | "general"
    """
    text = (text or "").strip()
    out = {
        "symptoms": [],
        "nutrition_mentions": [],
        "activity_mentions": [],
        "intent": "general",
    }
    if not text:
        return out

    lower = text.lower()
    words = set(re.findall(r"[а-яёa-z0-9]+", lower))

    scores = {"illness": 0, "nutrition": 0, "fitness": 0}
    for phrase in (
        "ничего не хочется",
        "не хочется",
        "апатия",
        "апатич",
        "уставш",
        "неохота",
        "выгорел",
    ):
        if phrase in lower:
            scores["illness"] += 2
    for w in _INTENT_ILLNESS:
        if _match_keyword(lower, words, w):
            scores["illness"] += 1
    for w in _INTENT_NUTRITION:
        if _match_keyword(lower, words, w):
            scores["nutrition"] += 1
    for w in _INTENT_FITNESS:
        if _match_keyword(lower, words, w):
            scores["fitness"] += 1

    if max(scores.values()) > 0:
        out["intent"] = max(scores, key=scores.get)

    # Простое извлечение: предложения с ключевыми словами как контекст
    for sent in re.split(r"[.!?]\s+", text):
        sent = sent.strip()
        if not sent or len(sent) < 3:
            continue
        s = sent.lower()
        sent_tokens = set(re.findall(r"[а-яёa-z0-9]+", s))
        if any(_match_keyword(s, sent_tokens, k) for k in _INTENT_ILLNESS):
            out["symptoms"].append(sent[:300])
        if any(_match_keyword(s, sent_tokens, k) for k in _INTENT_NUTRITION):
            out["nutrition_mentions"].append(sent[:300])
        if any(_match_keyword(s, sent_tokens, k) for k in _INTENT_FITNESS):
            out["activity_mentions"].append(sent[:300])

    out["symptoms"] = out["symptoms"][:10]
    out["nutrition_mentions"] = out["nutrition_mentions"][:5]
    out["activity_mentions"] = out["activity_mentions"][:5]
    return out
