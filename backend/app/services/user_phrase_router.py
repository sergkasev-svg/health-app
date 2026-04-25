"""Router for frequent real-world user phrases -> canonical complaint queries."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_PRESETS_FILE = _BACKEND_DIR / "data" / "user_phrase_presets_ru.json"
_CACHE: list[dict[str, Any]] | None = None


def _norm(text: str) -> str:
    t = str(text or "").strip().lower().replace("ё", "е")
    t = re.sub(r"[^\w\sа-яa-z0-9]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _load_items() -> list[dict[str, Any]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    if not _PRESETS_FILE.exists():
        _CACHE = []
        return _CACHE
    try:
        payload = json.loads(_PRESETS_FILE.read_text(encoding="utf-8"))
        items = payload.get("items") if isinstance(payload, dict) else []
        rows = [x for x in (items or []) if isinstance(x, dict)]
    except Exception:
        rows = []
    # Pre-normalize once for fast matching.
    out: list[dict[str, Any]] = []
    split_idx = max(1, len(rows) // 2)
    for idx, row in enumerate(rows):
        phrase = _norm(str(row.get("phrase") or ""))
        canonical_query = str(row.get("canonical_query") or "").strip()
        if not phrase or not canonical_query:
            continue
        ab_style = "A" if idx < split_idx else "B"
        out.append(
            {
                "phrase": phrase,
                "canonical_query": canonical_query,
                "tag": str(row.get("tag") or "").strip(),
                "raw_phrase": str(row.get("phrase") or "").strip(),
                "ab_style": ab_style,
                "preset_index": idx,
            }
        )
    _CACHE = out
    return _CACHE


def match_user_phrase_preset(message: str) -> dict[str, Any] | None:
    query = _norm(message)
    if not query:
        return None
    best: dict[str, Any] | None = None
    best_score = 0
    for row in _load_items():
        phrase = row["phrase"]
        score = 0
        if query == phrase:
            score = 1000 + len(phrase)
        elif phrase in query:
            score = 100 + len(phrase)
        elif len(query) >= 18 and query in phrase:
            score = 50 + len(query)
        if score > best_score:
            best_score = score
            best = row
    return best

