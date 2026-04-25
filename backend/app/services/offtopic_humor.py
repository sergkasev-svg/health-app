"""
Определение «непонятной» жалобы: при общем намерении (general) без явной темы здоровья
консультант задаёт наводящие вопросы вместо ответа. Алгоритм шуток удалён.
"""
from __future__ import annotations

import re


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _is_pure_greeting(msg: str) -> bool:
    t = _norm(msg)
    if not t:
        return True
    greetings = (
        "привет", "здравствуйте", "добрый день", "доброе утро", "добрый вечер",
        "hello", "hi", "как дела", "как ты",
    )
    return t in greetings


def _is_medical_like(msg: str) -> bool:
    t = _norm(msg)
    med = (
        "бол", "температ", "кашл", "горл", "давлен", "анализ", "диагноз", "лечение",
        "метеор", "вздут", "изжог", "запор", "диаре", "понос", "тошнот", "рвот",
        "газ", "пуч", "пука",
        "аллерг", "симптом", "препарат", "таблет", "врач",
        "плохо", "самочувств", "недомога", "отравл", "тошнит", "подташнива",
        "стало плохо", "мне плохо", "жалоб",
        "непереносимость", "гормональн", "подсолнечник", "помочь", "помогите",
        "кишечник", "тошнота", "проблема", "проблемы",
        "ухудшилось", "семечк", "поплохело", "поплохела",
        "жжет", "жжёт", "мочеисп", "выделен", "сып", "зуд", "отек", "отёк",
        "отвечать будешь", "описал жалобу", "не задал", "установить диагноз",
    )
    if any(k in t for k in med):
        return True
    food_ate = ("поел", "съел", "поела", "съела", "семена", "семечк")
    discomfort = ("плохо", "плохое", "тошно", "недомога", "болит", "больно", "дискомфорт", "ухудшилось", "поплохело", "поплохела")
    has_food = any(k in t for k in food_ate)
    has_discomfort = any(k in t for k in discomfort)
    if has_food and has_discomfort:
        return True
    return False


def would_ask_clarifying_instead_of_joke(user_message: str) -> bool:
    """True, если сообщение не приветствие и не по теме здоровья — показываем наводящие вопросы."""
    msg = _norm(user_message)
    if not msg:
        return False
    if _is_pure_greeting(msg):
        return False
    if _is_medical_like(msg):
        return False
    return True
