"""
База топ-20/топ-100 частых жалоб: офлайн + RAG для zazdorovie.ru.
Загружается top_complaints_100.json при наличии, иначе top_complaints_20.json.
Сопоставление по aliases, возврат red_flags, key_questions, likely_causes, home_advice, see_doctor_if.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.services.clinical_intent_semantics import topic_scores, topic_vector_cosine

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_TOP100_FILE = _PROJECT_ROOT / "medical_knowledge" / "top_complaints_100.json"
_TOP20_FILE = _PROJECT_ROOT / "medical_knowledge" / "top_complaints_20.json"
_CACHE: list[dict[str, Any]] | None = None
_LABEL: str = "топ-20"  # "топ-100" если загружен top_complaints_100.json


def _load_items() -> list[dict[str, Any]]:
    global _CACHE, _LABEL
    if _CACHE is not None:
        return _CACHE
    path = _TOP100_FILE if _TOP100_FILE.exists() else _TOP20_FILE
    _LABEL = "топ-100" if path == _TOP100_FILE else "топ-20"
    if not path.exists():
        _CACHE = []
        return _CACHE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _CACHE = []
        return _CACHE
    items = data.get("items") if isinstance(data, dict) else []
    _CACHE = [x for x in (items or []) if isinstance(x, dict)]
    return _CACHE


def get_top_complaints_label() -> str:
    """Возвращает подпись базы жалоб для промпта: «топ-100» или «топ-20»."""
    _load_items()
    return _LABEL


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def _item_semantic_blob(it: dict[str, Any]) -> str:
    """Текст для topic_scores: кластер, алиасы и клинические поля записи справочника."""
    parts: list[str] = []
    for key in (
        "symptom_cluster",
        "symptom_label",
        "title",
        "aliases",
        "likely_causes",
        "key_questions",
        "red_flags",
        "red_flags_specific",
        "home_advice",
        "see_doctor_if",
    ):
        v = it.get(key)
        if v is None:
            continue
        if isinstance(v, str):
            s = v.strip()
            if s:
                parts.append(s)
        elif isinstance(v, list):
            parts.extend(str(x).strip() for x in v if str(x).strip())
    return " ".join(parts) if parts else ""


def match_top20(user_message: str, top_k: int = 1) -> list[dict[str, Any]]:
    """
    Сопоставляет сообщение пользователя с кластерами по aliases.
    Возвращает до top_k записей с наибольшим совпадением.
    """
    msg = _normalize(user_message)
    if not msg or len(msg) < 2:
        return []
    words = set(re.findall(r"[а-яёa-z0-9]+", msg))
    words = {w for w in words if len(w) >= 2}
    if not words:
        return []
    items = _load_items()
    msg_topics = topic_scores(msg)
    scored: list[tuple[float, dict[str, Any]]] = []
    for it in items:
        aliases = [str(x or "").strip().lower() for x in (it.get("aliases") or []) if str(x).strip()]
        hay = " ".join(aliases)
        hits = sum(1 for w in words if w in hay)
        blob_vec = topic_scores(_item_semantic_blob(it))
        sem = topic_vector_cosine(msg_topics, blob_vec) if msg_topics and blob_vec else 0.0
        if hits <= 0 and sem < 0.22:
            continue
        exact_alias = 0
        for a in aliases:
            if a and a in msg:
                exact_alias = max(exact_alias, len(a))
        score = float(hits) + exact_alias * 0.01 + sem * 3.5
        scored.append((score, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in scored[: max(1, top_k)]]


def format_top20_for_prompt(entry: dict[str, Any]) -> str:
    """Форматирует запись топ-жалоб для вставки в промпт консьержа (топ-20 или топ-100)."""
    cluster = str(entry.get("symptom_cluster") or "").strip()
    red = entry.get("red_flags") or []
    questions = entry.get("key_questions") or []
    causes = entry.get("likely_causes") or []
    home = entry.get("home_advice") or []
    see = entry.get("see_doctor_if") or []
    label = get_top_complaints_label()
    lines = [
        "База " + label + " жалоб (офлайн): кластер «" + (cluster or "—") + "».",
        "Красные флаги (при упоминании — акцентировать срочность): " + "; ".join(red[:8]) if red else "",
        "Вопросы для уточнения: " + "; ".join(questions[:6]) if questions else "",
        "Вероятные причины: " + "; ".join(causes[:6]) if causes else "",
        "Рекомендации дома: " + "; ".join(home[:6]) if home else "",
        "Когда к врачу: " + "; ".join(see[:6]) if see else "",
    ]
    return "\n".join(l for l in lines if l.strip())
