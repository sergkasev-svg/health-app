"""
Смысловая близость жалобы к клиническим темам: не только отдельные ключи, но и устойчивые фразы (триггеры смысла).

Используется для снижения ложных срабатываний справочников и как дополнительный сигнал к правилам в user.py.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Any

_TOPIC_SPECS: dict[str, dict[str, Any]] = {
    "respiratory": {
        "tokens": (
            "кашл",
            "кашель",
            "мокрот",
            "насморк",
            "сопл",
            "горло",
            "горлит",
            "першит",
            "ангин",
            "фарингит",
            "орви",
            "простуд",
            "грипп",
            "озноб",
            "лихорад",
            "одышк",
            "чих",
            "бронхит",
            "пневмон",
        ),
        "phrases": (
            "кашель с мокрот",
            "насморк и",
            "боль в горле",
            "сухой кашель",
            "нет воздуха",
            "не хватает воздух",
        ),
    },
    "sexual_libido": {
        "tokens": (
            "либид",
            "либдо",
            "эректиль",
            "эрекц",
            "импотенц",
            "сексуальн",
            "интим",
            "полов акт",
            "половой",
            "эякуляц",
            "оргазм",
            "влечен",
        ),
        "phrases": (
            "снижен либид",
            "нет либид",
            "делать с либид",
            "про либид",
            "что с либид",
            "половое влечен",
        ),
    },
    "gastrointestinal": {
        "tokens": (
            "тошн",
            "рвот",
            "понос",
            "диаре",
            "живот бол",
            "боль в живот",
            "изжог",
            "стул",
            "запор",
            "жкт",
            "кишечн",
            "желуд",
        ),
        "phrases": (
            "жидкий стул",
            "боль внизу живот",
            "тошнит после еды",
        ),
    },
    "urogenital": {
        "tokens": (
            "цистит",
            "мочеиспуск",
            "моче",
            "уролог",
            "почк",
            "простат",
            "аденом",
            "уретр",
            "жжение при моч",
        ),
        "phrases": (
            "кровь в моче",
            "частое мочеиспускание",
            "резь при моч",
        ),
    },
    "gynecology": {
        "tokens": (
            "месячн",
            "менстру",
            "цикл",
            "овуляц",
            "беремен",
            "гинеколог",
            "матк",
            "яичник",
            "кольпит",
            "мастит",
            "лактац",
            "груд молок",
        ),
        "phrases": (
            "задержка месячн",
            "идут месячн",
            "боль при месячн",
        ),
    },
    "cardiovascular": {
        "tokens": (
            "сердц",
            "давлен",
            "гипертон",
            "тахикард",
            "аритм",
            "инфаркт",
            "стенокард",
            "груд бол",
            "боль в груди",
            "одышк в покое",
        ),
        "phrases": (
            "боль за грудин",
            "давит в груди",
        ),
    },
    "neuro": {
        "tokens": (
            "голов бол",
            "мигрен",
            "головокруж",
            "онемен",
            "инсульт",
            "эпилепс",
            "невролог",
        ),
        "phrases": (
            "сильная головная боль",
            "боль в затылк",
        ),
    },
    "dermatology": {
        "tokens": (
            "сыпь",
            "зуд",
            "кож",
            "дерматит",
            "экзем",
            "псориаз",
            "акне",
            "прыщ",
            "крапивниц",
        ),
        "phrases": (
            "сыпь по телу",
            "зуд кожи",
        ),
    },
    "endocrine": {
        "tokens": (
            "щитовид",
            "ттг",
            "тирео",
            "диабет",
            "сахарн",
            "инсулин",
            "глюкоз",
            "гипогликем",
            "пролактин",
            "кортизол",
        ),
        "phrases": (
            "анализ на ттг",
            "сахар крови",
        ),
    },
    "fatigue_systemic": {
        "tokens": (
            "усталост",
            "нет сил",
            "астен",
            "вялост",
            "апат",
            "выгоран",
            "переутомлен",
            "слабост",
        ),
        "phrases": (
            "нет сил встать",
            "не могу встать с кроват",
            "хроническая усталост",
        ),
    },
    "mental_stress": {
        "tokens": (
            "тревог",
            "паник",
            "депресс",
            "стресс",
            "бессон",
            "страх",
            "апат",
            "настроен",
            "психотерапевт",
        ),
        "phrases": (
            "паническая атак",
            "нет настроен",
            "плохо сплю",
        ),
    },
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def topic_scores(text: str) -> dict[str, float]:
    """Веса тем по тексту: токены + усиленные фразы (смысловые триггеры)."""
    t = _norm(text)
    if not t:
        return {}
    out: dict[str, float] = {}
    for topic, spec in _TOPIC_SPECS.items():
        s = 0.0
        for ph in spec.get("phrases", ()):
            if ph in t:
                s += 2.8
        for tok in spec.get("tokens", ()):
            if tok in t:
                s += 1.0
        if s > 0:
            out[topic] = s
    return out


def topic_vector_cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def semantic_topic_alignment(query: str, candidate_label: str) -> float:
    """
    Насколько «тема» текста запроса согласована с темой названия справочной строки (0..1).
    Короткие односложные названия получают низкий вектор — тогда опора на lexical score.
    """
    qv = topic_scores(query)
    cv = topic_scores(candidate_label)
    if not qv:
        return 0.55
    if not cv:
        return 0.35
    return topic_vector_cosine(qv, cv)


def query_topic_strength(query: str) -> float:
    """Насколько явно пользователь попал в одну или несколько тем (для порога доверия)."""
    qv = topic_scores(query)
    if not qv:
        return 0.0
    return float(max(qv.values()))


def combine_lexical_and_semantic_treatment_score(
    lexical_score: float,
    query: str,
    candidate_label: str,
    *,
    semantic_weight: float = 0.55,
) -> float:
    """
    Объединяет лексический матч и смысловое выравнивание тем.
    При сильной тематике запроса низкий semantic alignment сильнее опускает итог.
    """
    align = semantic_topic_alignment(query, candidate_label)
    base = float(lexical_score)
    strength = query_topic_strength(query)
    # Чем явнее тема в запросе, тем больше вес смысла.
    w = semantic_weight * min(1.0, strength / 3.5)
    combined = base * (1.0 - w) + (base * align) * w
    if strength >= 2.5 and align < 0.18:
        combined *= 0.35
    return combined


@lru_cache(maxsize=256)
def dominant_topic_tags(query: str) -> tuple[str, ...]:
    """Топ-темы по убыванию веса — для промптов и отладки."""
    qv = topic_scores(_norm(query))
    if not qv:
        return ()
    ranked = sorted(qv.items(), key=lambda x: -x[1])
    return tuple(t for t, _ in ranked[:4])


_TOPIC_HINT_RU: dict[str, str] = {
    "respiratory": "дыхание / ОРВИ / кашель",
    "sexual_libido": "либидо и сексуальное здоровье",
    "gastrointestinal": "желудок и кишечник",
    "urogenital": "мочеполовая система",
    "gynecology": "гинекология и цикл",
    "cardiovascular": "сердце и сосуды",
    "neuro": "неврология / головная боль",
    "dermatology": "кожа и аллергия",
    "endocrine": "эндокринология / обмен веществ",
    "fatigue_systemic": "усталость и астения",
    "mental_stress": "стресс / тревога / настроение",
}


def format_intent_hint_for_prompt(user_message: str) -> str:
    """Короткая строка для системного промпта: совокупность тем по ключам и фразам."""
    tags = dominant_topic_tags(user_message)
    if not tags:
        return ""
    parts = [_TOPIC_HINT_RU.get(t, t.replace("_", " ")) for t in tags[:4]]
    return (
        "Смысловые темы реплики пользователя (ключи + устойчивые фразы): "
        + "; ".join(parts)
        + ". Сохраняй ответ в этом смысле, если он согласуется с текстом."
    )
