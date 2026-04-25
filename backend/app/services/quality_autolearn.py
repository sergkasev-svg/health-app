"""
Lightweight auto-learning loop for concierge relevance:
- detect topic mismatch between user question and assistant answer
- accumulate collision stats
- provide conflicting topic keywords for runtime filtering
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Set


_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_QUALITY_DIR = _BACKEND_DIR / "data" / "quality"
_COLLISIONS_FILE = _QUALITY_DIR / "topic_collisions.json"


TOPIC_KEYWORDS: Dict[str, tuple[str, ...]] = {
    "gi_gas": ("вздут", "метеор", "газообраз", "газы", "урчани"),
    "reflux": ("изжог", "рефлюкс", "гэрб", "кислот", "горечь"),
    "constipation": ("запор", "редкий стул", "твердый стул", "твёрдый стул"),
    "diarrhea": ("диаре", "понос", "жидкий стул", "частый стул"),
    "pressure": ("давлен", "гипертенз", "гипертони"),
    "respiratory": ("кашл", "горл", "насморк", "сопл", "одыш", "хрип"),
    "headache": ("головн", "мигрен"),
    "joint": ("сустав", "артрит", "артроз"),
}


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _norm(s: str) -> str:
    return " ".join(str(s or "").lower().strip().split())


def detect_topics(text: str) -> Set[str]:
    t = _norm(text)
    if not t:
        return set()
    out: Set[str] = set()
    for topic, keys in TOPIC_KEYWORDS.items():
        if any(k in t for k in keys):
            out.add(topic)
    return out


def record_turn_for_autolearn(question: str, answer: str) -> None:
    q_topics = detect_topics(question or "")
    a_topics = detect_topics(answer or "")
    if not q_topics or not a_topics:
        return
    if q_topics & a_topics:
        return
    data = _read_json(_COLLISIONS_FILE)
    matrix = data.get("matrix") or {}
    for qt in q_topics:
        row = matrix.get(qt) or {}
        for at in a_topics:
            row[at] = int(row.get(at) or 0) + 1
        matrix[qt] = row
    data["matrix"] = matrix
    _write_json(_COLLISIONS_FILE, data)


def get_conflicting_topics(source_topics: Set[str], min_hits: int = 1) -> Set[str]:
    if not source_topics:
        return set()
    data = _read_json(_COLLISIONS_FILE)
    matrix = data.get("matrix") or {}
    out: Set[str] = set()
    for st in source_topics:
        row = matrix.get(st) or {}
        for topic, cnt in row.items():
            if int(cnt or 0) >= int(min_hits):
                out.add(topic)
    return out


def topic_keywords(topic: str) -> tuple[str, ...]:
    return TOPIC_KEYWORDS.get(topic, ())

