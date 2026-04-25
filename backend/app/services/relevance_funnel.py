from __future__ import annotations

import re
from typing import Any


_RESPIRATORY_KEYS = (
    "бронхит",
    "орви",
    "трахеит",
    "фарингит",
    "тонзиллит",
    "пневмон",
    "каш",
    "мокрот",
    "насморк",
    "сопл",
    "простуд",
)
_FOOD_HEADACHE_KEYS = (
    "мигр",
    "головн",
    "пищев",
    "тирамин",
    "гистамин",
    "лактоз",
    "триггер",
    "неперенос",
)
_GI_KEYS = ("жкт", "гастр", "рефлюкс", "изжог", "кишеч", "диспепс")


def _contains_any(text: str, parts: tuple[str, ...]) -> bool:
    low = (text or "").lower()
    return any(p in low for p in parts)


def build_funnel_tags(user_message: str) -> dict[str, bool]:
    low = (user_message or "").lower()
    has_headache = _contains_any(low, ("голов", "мигр", "цефал"))
    has_post_food = _contains_any(low, ("после еды", "после", "через", "после того", "после того как"))
    has_dairy = _contains_any(low, ("сыр", "творог", "молоко", "молоч", "йогурт", "кефир"))
    has_respiratory = _contains_any(low, _RESPIRATORY_KEYS)
    return {
        "food_headache": bool(has_headache and has_post_food and has_dairy),
        "respiratory_context": bool(has_respiratory),
        "gi_context": bool(_contains_any(low, ("живот", "жкт", "тошн", "рвот", "понос", "диаре", "изжог", "вздут"))),
    }


def _score_candidate(label: str, source: str, tags: dict[str, bool]) -> int:
    low = (label or "").lower()
    score = 0
    if source == "strict_protocol":
        score += 3
    elif source in ("clinical_profiles", "diagnostic_engine"):
        score += 2
    elif source in ("food_trigger_rules", "symptom_cause_graph"):
        score += 2

    if tags.get("food_headache"):
        if _contains_any(low, _FOOD_HEADACHE_KEYS):
            score += 5
        if _contains_any(low, _RESPIRATORY_KEYS):
            score -= 8
    if tags.get("gi_context") and _contains_any(low, _GI_KEYS):
        score += 2
    if tags.get("respiratory_context") and _contains_any(low, _RESPIRATORY_KEYS):
        score += 3
    return score


def apply_relevance_funnel(user_message: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Lightweight relevance funnel:
    1) gather all candidate labels from different sources
    2) score by context
    3) keep only relevant branch(es), drop drift
    """
    tags = build_funnel_tags(user_message)
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in candidates or []:
        label = str((c or {}).get("label") or "").strip()
        source = str((c or {}).get("source") or "").strip()
        if not label:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        score = _score_candidate(label, source, tags)
        row = {"label": label, "source": source, "score": score}
        hard_drop = bool(tags.get("food_headache") and not tags.get("respiratory_context") and _contains_any(key, _RESPIRATORY_KEYS))
        if hard_drop or score < 0:
            dropped.append(row)
        else:
            kept.append(row)
    kept.sort(key=lambda x: x.get("score", 0), reverse=True)
    dropped.sort(key=lambda x: x.get("score", 0))
    top_labels = [str(x.get("label") or "").strip() for x in kept[:5] if str(x.get("label") or "").strip()]
    return {
        "tags": tags,
        "kept": kept[:8],
        "dropped": dropped[:8],
        "top_labels": top_labels,
        "block_respiratory_drift": bool(tags.get("food_headache") and not tags.get("respiratory_context")),
    }


def scrub_text_with_funnel(user_message: str, text: str, block_respiratory_drift: bool | None = None) -> str:
    src = str(text or "").strip()
    if not src:
        return src
    tags = build_funnel_tags(user_message)
    should_block = bool(block_respiratory_drift) if block_respiratory_drift is not None else bool(
        tags.get("food_headache") and not tags.get("respiratory_context")
    )
    if not should_block:
        return src
    lines = []
    for line in src.splitlines():
        low = line.lower()
        if _contains_any(low, _RESPIRATORY_KEYS):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    return cleaned or src
