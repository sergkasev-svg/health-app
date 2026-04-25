from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable


def normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = text.replace("ё", "е")
    text = re.sub(r"[^\w\s-]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)
    return text


def tokenize(text: str) -> list[str]:
    return [t for t in normalize_text(text).split() if t]


def contains_phrase(text: str, phrase: str) -> bool:
    return normalize_text(phrase) in normalize_text(text)


def fuzzy_contains(text: str, phrase: str, threshold: float = 0.86) -> bool:
    """
    Lightweight fuzzy phrase matcher.
    Good enough for short colloquial variants like:
    'подташнивает', 'раздуло', 'тянет справа', etc.
    """
    norm_text = normalize_text(text)
    norm_phrase = normalize_text(phrase)

    if norm_phrase in norm_text:
        return True

    text_tokens = tokenize(norm_text)
    phrase_tokens = tokenize(norm_phrase)

    if not phrase_tokens or not text_tokens:
        return False

    window = len(phrase_tokens)
    if window <= 0:
        return False

    if len(text_tokens) < window:
        candidates = [" ".join(text_tokens)]
    else:
        candidates = [
            " ".join(text_tokens[i : i + window])
            for i in range(0, len(text_tokens) - window + 1)
        ]

    for chunk in candidates:
        ratio = SequenceMatcher(None, chunk, norm_phrase).ratio()
        if ratio >= threshold:
            return True

    return False


def match_any(
    text: str,
    phrases: Iterable[str],
    *,
    allow_fuzzy: bool = True,
    threshold: float = 0.86,
) -> list[str]:
    matched: list[str] = []
    for phrase in phrases:
        if contains_phrase(text, phrase):
            matched.append(phrase)
            continue
        if allow_fuzzy and fuzzy_contains(text, phrase, threshold=threshold):
            matched.append(phrase)
    return list(dict.fromkeys(matched))

