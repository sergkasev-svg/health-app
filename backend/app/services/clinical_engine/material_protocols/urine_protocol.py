"""Протокол мочи: ОАМ, суточная, микроальбумин, ОК в моче."""
from __future__ import annotations

URINE_ANCHOR_PHRASES = (
    "общий анализ мочи",
    "оам",
    "анализ мочи",
    "urinalysis",
    "биоматериал: моча",
    "биоматериал моча",
    "моча (разовая)",
    "моча разовая",
    "количество мочи",
)

URINE_MARKER_KEYWORDS = (
    "относительная плотность",
    "удельный вес",
    "плотность мочи",
    "нитриты",
    "уробилиноген",
    "реакция на кровь",
    "бактерии",
    "цилиндры",
    "осадок",
    "кетоны",
    "билирубин",
    "лейкоцит",
    "эритроцит",
    "слизь",
    "соли",
    "кислотность",
)


def urine_anchor_hit(text: str) -> bool:
    low = (text or "").lower()
    return any(p in low for p in URINE_ANCHOR_PHRASES)


def urine_marker_count(text: str) -> int:
    low = (text or "").lower()
    return sum(1 for m in URINE_MARKER_KEYWORDS if m in low)


def is_strong_urine(text: str) -> bool:
    """Явный ОАМ / биоматериал моча или много маркеров мочи."""
    low = (text or "").lower()
    if urine_anchor_hit(text):
        return True
    # как в legacy: много маркеров без явного «кровь»
    n = urine_marker_count(text)
    if n >= 5:
        return True
    if urine_anchor_hit(text) and n >= 4:
        return True
    # типичная связка ОАМ
    if "ph" in low and ("плотност" in low or "удельн" in low or "относительн" in low):
        if "нитрит" in low or "лейкоцит" in low or "белок" in low:
            return True
    return False
