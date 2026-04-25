"""Протокол слюны: кортизол, ДНК, гормоны."""
from __future__ import annotations

SALIVA_MARKERS = (
    "слюна",
    "saliva",
    "слюнн",
    "кортизол в слюне",
    "слюнной",
)


def is_saliva(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in SALIVA_MARKERS)
