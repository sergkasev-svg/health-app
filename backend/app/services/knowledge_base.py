"""
Knowledge Base service — loads local JSON scenarios and provides
context injection for the AI chat.

Usage:
    from app.services.knowledge_base import get_scenario_context

    context = get_scenario_context("high_cortisol")   # by id
    context = search_scenario_context("головная боль тревога")  # by symptom text
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Resolve path relative to this file so it works from any CWD.
_KB_PATH = Path(__file__).parent.parent.parent.parent / "frontend" / "public" / "data" / "knowledge_base.json"
_BIOMARKERS_PATH = Path(__file__).parent.parent.parent.parent / "frontend" / "public" / "data" / "biomarkers.json"

_data: Optional[dict] = None
_biomarkers_data: Optional[dict] = None


def _load() -> Optional[dict]:
    global _data
    if _data is not None:
        return _data
    try:
        with open(_KB_PATH, encoding="utf-8") as f:
            _data = json.load(f)
        logger.info("[KB] Loaded %d scenarios", len(_data.get("scenarios", [])))
    except FileNotFoundError:
        logger.warning("[KB] knowledge_base.json not found at %s", _KB_PATH)
        _data = {}
    except Exception as exc:
        logger.exception("[KB] Failed to load knowledge_base.json: %s", exc)
        _data = {}
    return _data


def _load_biomarkers() -> Optional[dict]:
    global _biomarkers_data
    if _biomarkers_data is not None:
        return _biomarkers_data
    try:
        with open(_BIOMARKERS_PATH, encoding="utf-8") as f:
            _biomarkers_data = json.load(f)
        n = len(_biomarkers_data.get("items", []))
        logger.info("[KB] Loaded %d biomarker reference entries", n)
    except FileNotFoundError:
        logger.warning("[KB] biomarkers.json not found at %s", _BIOMARKERS_PATH)
        _biomarkers_data = {}
    except Exception as exc:
        logger.exception("[KB] Failed to load biomarkers.json: %s", exc)
        _biomarkers_data = {}
    return _biomarkers_data


def search_biomarkers_context(query: str, top_k: int = 4) -> str:
    """
    Найти релевантные записи справочника биомаркеров по тексту запроса.
    Возвращает блок для инъекции в промпт (пустая строка при отсутствии совпадений).
    """
    if not query or not str(query).strip():
        return ""
    data = _load_biomarkers()
    items = data.get("items") if isinstance(data, dict) else None
    if not items:
        return ""
    q = str(query).lower().strip()
    tokens = [t for t in q.replace(",", " ").split() if len(t) > 2]
    if not tokens:
        tokens = [q]

    scored: list[tuple[int, dict]] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        blob_parts = [
            entry.get("name", ""),
            entry.get("category", ""),
            entry.get("matrix", ""),
            entry.get("brief", ""),
            entry.get("ref_text", ""),
            " ".join(entry.get("aliases") or []),
            " ".join(entry.get("panels") or []),
        ]
        blob = " ".join(str(x) for x in blob_parts).lower()
        score = sum(1 for t in tokens if t in blob)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [e for _, e in scored[:top_k]]
    if not picked:
        return ""

    lines = ["[СПРАВОЧНИК БИОМАРКЕРОВ — выдержки по запросу]"]
    disc = (data or {}).get("disclaimer")
    if disc:
        lines.append(str(disc))
    for e in picked:
        name = e.get("name", "")
        cat = e.get("category", "")
        matrix = e.get("matrix", "")
        ref_t = e.get("ref_text", "")
        brief = e.get("brief", "")
        lines.append(f"- {name} ({cat}, {matrix}): референсы ориентировочно: {ref_t}. Кратко: {brief}")
    return "\n".join(lines)


def get_scenario_by_id(scenario_id: str) -> Optional[dict]:
    """Return a scenario dict by exact id, or None."""
    data = _load()
    for sc in data.get("scenarios", []):
        if sc.get("id") == scenario_id:
            return sc
    return None


def search_scenarios(query: str, top_k: int = 1) -> list[dict]:
    """
    Simple keyword search across scenario symptoms / name / context.
    Returns up to top_k matching scenario dicts.
    """
    if not query:
        return []
    data = _load()
    tokens = [t.lower() for t in query.split() if len(t) > 2]
    if not tokens:
        tokens = [query.lower().strip()]

    scored: list[tuple[int, dict]] = []
    for sc in data.get("scenarios", []):
        blob = " ".join([
            sc.get("name", ""), sc.get("name_en", ""), sc.get("context", ""),
            " ".join(sc.get("symptoms", [])),
            " ".join(sc.get("recommendations", [])),
        ]).lower()
        score = sum(1 for t in tokens if t in blob)
        if score > 0:
            scored.append((score, sc))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [sc for _, sc in scored[:top_k]]


def build_scenario_context(scenario: dict) -> str:
    """
    Build a concise context string from a scenario dict,
    suitable for injection into the AI system prompt.
    """
    if not scenario:
        return ""
    lines = [f"[МЕДИЦИНСКИЙ СЦЕНАРИЙ: {scenario.get('name', '')}]"]

    symptoms = scenario.get("symptoms", [])
    if symptoms:
        lines.append("Симптомы пациента: " + ", ".join(symptoms))

    markers = scenario.get("lab_markers", [])
    if markers:
        lines.append("Лабораторные показатели:")
        for m in markers:
            icon = "↑" if m.get("status") == "HIGH" else ("↓" if m.get("status") == "LOW" else "✓")
            lines.append(f"  {icon} {m.get('name')}: {m.get('value')} (норма: {m.get('norm')})")

    context = scenario.get("context", "")
    if context:
        lines.append(f"Клинический контекст: {context}")

    recs = scenario.get("recommendations", [])
    if recs:
        lines.append("Рекомендуемые действия: " + "; ".join(recs))

    return "\n".join(lines)


def get_scenario_context(scenario_id: str) -> str:
    """Convenience: get context string by scenario id (empty string if not found)."""
    sc = get_scenario_by_id(scenario_id)
    return build_scenario_context(sc) if sc else ""


def search_scenario_context(query: str) -> str:
    """
    Find the most relevant scenario by symptom query and return its context string.
    Appends biomarker dictionary excerpts when the query matches lab analyte names.
    Returns empty string if no relevant scenario and no biomarkers found.
    """
    results = search_scenarios(query, top_k=1)
    scenario_ctx = build_scenario_context(results[0]) if results else ""
    bio_ctx = search_biomarkers_context(query, top_k=4)
    if scenario_ctx and bio_ctx:
        return scenario_ctx + "\n\n" + bio_ctx
    if scenario_ctx:
        return scenario_ctx
    return bio_ctx
