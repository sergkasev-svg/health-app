"""
Strict topic protocol resolver.
Loads prebuilt strict protocols and returns highest-relevance item for a query.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_PROTOCOL_FILE = _PROJECT_ROOT / "medical_knowledge" / "diseases" / "strict_topic_protocols_350_plus.json"
_CACHE: list[dict[str, Any]] | None = None
_GENERIC_QUERY_WORDS = {
    "боль", "болит", "живот", "живота", "голова", "горло", "кашель", "насморк",
    "симптом", "симптомы", "причина", "лечение", "что", "делать", "как", "мне", "меня",
    "сильный", "сильная", "сильное", "долго", "давно",
}
_DOMAIN_RULES = {
    "gi": ("гастро", "жкт", "живот", "кишеч", "вздут", "метеор", "изжог", "рефлюкс", "запор", "диаре", "понос", "тошнот", "рвот", "газообраз"),
    "respiratory": ("дых", "кашл", "горл", "насморк", "сопл", "одыш", "хрип", "бронх", "пневм", "орз", "орви"),
    "cardio": ("серд", "груд", "тахик", "аритм", "давлен", "гиперт", "кардио"),
    "neuro": ("голов", "мигрен", "невр", "судорог", "инсульт", "головокруж"),
    "uro": ("моч", "цистит", "уролог", "почки", "урин", "пиело"),
    "skin": ("кож", "сып", "зуд", "дермат", "экзем", "акне"),
    "endo": ("эндокрин", "диаб", "глюкоз", "щитовид", "гормон", "ттг"),
}


def _load_items() -> list[dict[str, Any]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    if not _PROTOCOL_FILE.exists():
        _CACHE = []
        return _CACHE
    try:
        payload = json.loads(_PROTOCOL_FILE.read_text(encoding="utf-8"))
    except Exception:
        _CACHE = []
        return _CACHE
    items = payload.get("items") if isinstance(payload, dict) else []
    _CACHE = [x for x in (items or []) if isinstance(x, dict)]
    return _CACHE


def _tokens(text: str) -> set[str]:
    s = re.sub(r"[^\w\sа-яёa-z0-9]", " ", (text or "").lower())
    out = set()
    for w in s.split():
        if len(w) < 3:
            continue
        out.add(w)
    return out


def _infer_domain(text: str) -> str:
    low = (text or "").lower()
    if ("жаж" in low and "моч" in low) or ("сухость во рту" in low and "моч" in low):
        return "endo"
    for domain, hints in _DOMAIN_RULES.items():
        if any(h in low for h in hints):
            return domain
    return "general"


def search_strict_topic_protocol(query: str, top_k: int = 1) -> list[dict[str, Any]]:
    words = _tokens(query)
    if not words:
        return []
    focus_words = {w for w in words if w not in _GENERIC_QUERY_WORDS}
    if not focus_words:
        focus_words = set(words)
    query_domain = _infer_domain(query)
    rows = _load_items()
    if not rows:
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    for it in rows:
        title = str(it.get("title") or "").lower()
        diagnosis = str(it.get("diagnosis") or "").lower()
        keywords = [str(x).lower() for x in (it.get("keywords") or []) if str(x).strip()]
        hay = " ".join([title, diagnosis, " ".join(keywords)])
        focus_hits = sum(1 for w in focus_words if w in hay)
        if focus_hits <= 0:
            continue
        hits = sum(1 for w in words if w in hay)
        title_hits = sum(1 for w in words if w in title)
        kw_hits = sum(1 for w in words if any(w in k for k in keywords))
        type_boost = 0.35 if str(it.get("type") or "") == "complaint" else 0.2
        item_domain = str(it.get("domain") or "general")
        if query_domain != "general" and item_domain != "general" and item_domain != query_domain:
            continue
        domain_boost = 0.0
        if query_domain != "general":
            if item_domain == query_domain:
                domain_boost = 2.2
            elif item_domain == "general":
                domain_boost = -0.8
        learned_penalty = -0.35 if isinstance(it.get("learning_meta"), dict) else 0.0
        score = float(hits + focus_hits * 2.2 + title_hits * 1.8 + kw_hits * 1.3 + type_boost + domain_boost + learned_penalty)
        scored.append((score, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in scored[: max(1, top_k)]]

