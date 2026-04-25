"""
Стратегии снижения веса по типу пользователя (эвристика по тексту жалобы + контекст).

Публичные поля для клиента / логов: user_type, strategy, plan (как в контракте продукта).
"""
from __future__ import annotations

import re
from typing import Any

# Полный эталон для типа «застой / всё пробовал» (бывший WEIGHT_LOSS_PLATEAU_CANONICAL_REPLY_RU).
FIND_THE_BLOCK_REPLY_RU = """Слышу вас.

Если вес не снижается уже год, несмотря на попытки — это не про «силу воли». Обычно есть факторы, которые мешают организму.

Хорошая новость: в большинстве случаев это решается, и это действительно не так сложно, как кажется — важно навести порядок в базовых вещах.

Что можно сделать:

— Питание:
• сделайте его регулярным (2–3 основных приёма пищи без постоянных перекусов)
• уменьшите сладкое и мучное — именно они чаще всего «ломают» снижение веса
• добавляйте белок в каждый приём пищи (он даёт сытость)

— Время еды:
• старайтесь есть в одно и то же время
• последний приём пищи — за 2–3 часа до сна (не обязательно строго в 18:00)

— Вода:
• пейте достаточно воды в течение дня
• после еды можно пить, но спокойно, без больших объёмов

— Активность:
• начните с доступного уровня — даже 5–7 тысяч шагов уже хорошо
• постепенно можно выйти на 8–10 тысяч шагов или больше
• главное — регулярность, а не «сразу много»

— Контроль:
• взвешиваться можно, но лучше 1–2 раза в неделю, чтобы не зацикливаться

Важно:
слишком жёсткие ограничения (резко убрать всё, много спорта сразу) часто дают обратный эффект — откаты и усталость.

Что стоит проверить (если вес стоит):
— глюкоза и инсулин
— ТТГ
— ферритин
— витамин D"""


def _norm_blob(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().replace("ё", "е")).strip()


def _user_text_blob(case_state: dict[str, Any] | None) -> str:
    if not case_state:
        return ""
    parts = [
        str(case_state.get("chief_complaint") or ""),
        str(case_state.get("conversation_context") or ""),
        str(case_state.get("normalized_text") or ""),
    ]
    return _norm_blob(" ".join(p for p in parts if p))


def classify_weight_loss_user_type(case_state: dict[str, Any] | None) -> str:
    """
    Внутренний ключ стратегии:
    minimal_effort | control_system | no_restrictions | find_the_block | fast_start
    """
    t = _user_text_blob(case_state)
    if not t:
        return "find_the_block"

    if any(
        x in t
        for x in (
            "срочно похуд",
            "быстро похуд",
            "быстрее",
            "за недел",
            "за 2 недел",
            "за две недел",
            "за месяц",
            "к лету",
            "к отпуск",
            "к новому году",
            "20 кг",
            "10 кг за",
            "15 кг за",
        )
    ):
        return "fast_start"

    if any(
        x in t
        for x in (
            "уже год",
            "уже полгода",
            "целый год",
            "больше года",
            "несколько лет",
            "все пробовал",
            "всё пробовал",
            "пробовал всё",
            "пробовал все",
            "ничего не помогает",
            "вес стоит",
            "вес не уходит",
            "вес не снижается",
            "не худею",
            "не худеет",
            "не сбрасывается",
            "плато",
        )
    ):
        return "find_the_block"

    if any(
        x in t
        for x in (
            "срываюсь",
            "срыв",
            "сорвал",
            "заедаю",
            "заеда",
            "ем от стресса",
            "есть от стресса",
            "чувствую вину",
            "вина",
            "бросаю",
            "бросил",
            "опять сорвал",
            "эмоцион",
            "тревог",
        )
    ):
        return "no_restrictions"

    if any(
        x in t
        for x in (
            "калори",
            "ккал",
            "считаю",
            "трекер",
            "цифры",
            "макрос",
            "бжу",
            "дефицит калор",
            "контрол",
            "система питан",
            "люблю считать",
        )
    ):
        return "control_system"

    if any(
        x in t
        for x in (
            "не хочу напрягаться",
            "без напряга",
            "не могу себя заставить",
            "не могу заставить себя",
            "лень",
            "ленив",
            "перегружен",
            "перегруз",
            "нет энерг",
            "нет сил",
            "устал",
            "устала",
            "усталый",
            "усталость",
            "минимум усилий",
        )
    ):
        return "minimal_effort"

    return "find_the_block"


_STRATEGY_SPECS: dict[str, dict[str, Any]] = {
    "minimal_effort": {
        "user_type": "lazy_overloaded",
        "strategy": "minimum_efforts",
        "title": "Минимум усилий",
        "goal": "начать без стресса",
        "rules": ("ничего не считать", "не менять всё сразу"),
        "actions": (
            "убрать сладкие напитки",
            "есть 2–3 раза в день (без постоянных перекусов)",
            "ходьба 5–7 тысяч шагов",
        ),
        "key": "сделай чуть лучше, чем было",
        "intro": "Похоже, сейчас важнее не «идеальный план», а мягкий старт без перегруза.",
    },
    "control_system": {
        "user_type": "disciplined",
        "strategy": "control_and_system",
        "title": "Контроль и система",
        "goal": "точный дефицит калорий и предсказуемый прогресс",
        "rules": ("фиксировать данные", "не менять правила каждые два дня"),
        "actions": (
            "считать калории (или хотя бы порции + белок)",
            "белок ориентировочно 1,2–1,6 г/кг веса в день — если нет противопоказаний, уточните норму с врачом",
            "фиксировать вес 1–2 раза в неделю",
            "шаги + силовые/домашние тренировки по возможности",
        ),
        "key": "система даёт результат",
        "intro": "Похоже, вам заходит формат «цифры + регулярность» — это можно использовать как сильную сторону.",
    },
    "no_restrictions": {
        "user_type": "emotional",
        "strategy": "no_restrictions",
        "title": "Без жёстких запретов",
        "goal": "снизить срывы и стабилизировать питание",
        "rules": ("не запрещать всё полностью", "оставить заранее выбранные «разрешённые» сладости в малых порциях"),
        "actions": (
            "регулярные основные приёмы пищи",
            "не допускать сильного голода (часто он запускает срыв)",
            "план перекуса: заранее, а не «как получится»",
        ),
        "key": "стабильность важнее идеальности",
        "intro": "Если часто бывают срывы и чувство вины — жёсткие запреты обычно ухудшают картину.",
    },
    "find_the_block": {
        "user_type": "plateau",
        "strategy": "find_the_block",
        "title": "Найти блок",
        "goal": "найти причину, а не усиливать самокритику",
        "rules": (),
        "actions": (),
        "key": "проблема не в вас — часто она в скрытых калориях, сне, стрессе или гормонах",
        "intro": "",
    },
    "fast_start": {
        "user_type": "quick_result",
        "strategy": "fast_start",
        "title": "Быстрый старт",
        "goal": "быстрый ощутимый эффект, затем закрепление",
        "rules": ("не держать экстремальный режим месяцами", "после 2–3 недель — смягчение к устойчивому формату"),
        "actions": (
            "убрать сладкое и мучное на ближайшие 2–3 недели",
            "2–3 основных приёма пищи",
            "активность каждый день (шаги + короткие сессии)",
        ),
        "key": "сначала быстрый результат, потом стабилизация",
        "intro": "Если хочется «пощупать результат» быстро — можно начать с более плотного окна изменений, но без бесконечного жёсткого режима.",
    },
}


def build_weight_loss_strategy_struct(case_state: dict[str, Any] | None) -> dict[str, Any]:
    """Словарь для API / structured: user_type, strategy, plan."""
    key = classify_weight_loss_user_type(case_state)
    spec = dict(_STRATEGY_SPECS.get(key) or _STRATEGY_SPECS["find_the_block"])
    plan: list[str] = []
    for r in spec.get("rules") or ():
        if r:
            plan.append(f"правило: {r}")
    for a in spec.get("actions") or ():
        if a:
            plan.append(f"действие: {a}")
    if key == "find_the_block":
        plan = [
            "питание: скрытые калории, напитки, соусы, перекусы",
            "сон: 7–9 часов, стабильный подъём",
            "стресс: триггеры заедания",
            "анализы: глюкоза/инсулин, ТТГ, ферритин, витамин D — по согласованию с врачом",
        ]
    out = {
        "user_type": spec.get("user_type"),
        "strategy": spec.get("strategy"),
        "plan": plan,
        "engine_key": key,
    }
    return out


def _format_strategy_reply(key: str) -> str:
    if key == "find_the_block":
        return FIND_THE_BLOCK_REPLY_RU.strip()
    spec = _STRATEGY_SPECS[key]
    lines: list[str] = ["Слышу вас."]
    intro = str(spec.get("intro") or "").strip()
    if intro:
        lines.append("")
        lines.append(intro)
    lines.append("")
    lines.append(f"Стратегия: {spec['title']}")
    lines.append(f"Цель: {spec['goal']}")
    rules = tuple(spec.get("rules") or ())
    actions = tuple(spec.get("actions") or ())
    if rules:
        lines.append("")
        lines.append("Правила:")
        for r in rules:
            lines.append(f"— {r}")
    if actions:
        lines.append("")
        lines.append("Действия:")
        for a in actions:
            lines.append(f"— {a}")
    lines.append("")
    lines.append(f"Ключ: «{spec['key']}»")
    lines.append("")
    lines.append(
        "Если одним сообщением ответите, что ближе: «устал и без напряга», «люблю цифры», "
        "«часто срываюсь», «вес стоит при усилиях» или «нужен быстрый старт» — подстрою следующий шаг точнее."
    )
    return "\n".join(lines).strip()


def compose_weight_loss_branch_reply(case_state: dict[str, Any] | None) -> str:
    """Текст ответа ветки weight_loss_plateau для response_composer."""
    key = classify_weight_loss_user_type(case_state)
    return _format_strategy_reply(key)


__all__ = [
    "FIND_THE_BLOCK_REPLY_RU",
    "build_weight_loss_strategy_struct",
    "classify_weight_loss_user_type",
    "compose_weight_loss_branch_reply",
]
