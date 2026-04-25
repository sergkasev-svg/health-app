# -*- coding: utf-8 -*-
"""
Генерация уточняющих вопросов по симптомам (семантические шаблоны).
"""
from __future__ import annotations

QUESTION_TEMPLATES: dict[str, str] = {
    "pain": "Где именно ощущается боль?",
    "fever": "Поднималась ли температура?",
    "injury": "Была ли травма или падение?",
    "urination": "Есть ли жжение при мочеиспускании?",
    "duration": "Как давно это началось?",
    "intensity": "Насколько выражен симптом по шкале от 0 до 10?",
}


def generate_questions(symptoms: list[str]) -> list[str]:
    """По списку симптомов (нормализованных или сырых) возвращает список уникальных вопросов."""
    if not symptoms:
        return []
    t = " ".join(symptoms).lower()
    questions: list[str] = []
    if "боль" in t or "болит" in t or "pain" in t:
        questions.append(QUESTION_TEMPLATES["pain"])
    if "температур" in t or "жар" in t or "лихорад" in t or "fever" in t:
        questions.append(QUESTION_TEMPLATES["fever"])
    if "травм" in t or "удар" in t or "падени" in t or "подвернул" in t or "injury" in t:
        questions.append(QUESTION_TEMPLATES["injury"])
    if "моч" in t or "писать" in t or "urination" in t or "жжени" in t:
        questions.append(QUESTION_TEMPLATES["urination"])
    questions = list(dict.fromkeys(questions))
    return questions[:4]
