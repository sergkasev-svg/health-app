"""Мазки слизистых, ПЦР урогенитальные/ЛОР."""
from __future__ import annotations

SWAB_MARKERS = (
    "мазок",
    "swab",
    "соскоб",
    "урогенитал",
    "цервик",
    "уретр",
    "зев",
    "носоглот",
    "пцр",
    "днк ",
    "dna ",
    "н. гонор",
    "хламид",
    "микоплазм",
)


def swab_strength(text: str) -> int:
    low = (text or "").lower()
    return sum(1 for m in SWAB_MARKERS if m in low)


def is_strong_swab(text: str) -> bool:
    return swab_strength(text) >= 2
