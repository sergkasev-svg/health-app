"""Протокол кала: копрограмма, скрытая кровь, паразиты."""
from __future__ import annotations

STOOL_MARKERS = (
    "копрограмма",
    "кал",
    "stool",
    "feces",
    "фекал",
    "стеркобилин",
    "скрытая кровь",
    "яйца гельминт",
    "паразит",
    "цисты",
    "мышечные волокна",
    "жирные кислоты",
    "кислотность кала",
)


def stool_strength(text: str) -> int:
    low = (text or "").lower()
    return sum(1 for m in STOOL_MARKERS if m in low)


def is_strong_stool(text: str) -> bool:
    low = (text or "").lower()
    if "копрограмма" in low or "скрытая кровь" in low:
        return True
    return stool_strength(text) >= 3
