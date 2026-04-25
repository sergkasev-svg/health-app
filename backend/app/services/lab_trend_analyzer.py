"""
Анализ динамики лабораторных показателей по памяти сессии.
Умеет: последнее значение, история по маркеру, сравнение двух последних, суммари трендов.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.mikhail_memory import LabRecord, MikhailSessionMemory


MARKER_ALIASES: Dict[str, List[str]] = {
    "hemoglobin": ["гемоглобин", "hemoglobin", "hgb", "hb"],
    "mch": ["mch", "среднее содержание гемоглобина", "среднее сод. гемоглобина"],
    "wbc": ["лейкоцит", "wbc", "white blood"],
    "tsh": ["tsh", "тиреотропный", "тиротропин"],
    "free_t4": ["free t4", "свободный т4", "ft4", "св. т4"],
    "eosinophils": ["эозинофил", "eosinophil", "eos"],
    "ferritin": ["ферритин", "ferritin"],
}


def _normalize_marker_name(name: str) -> str:
    n = (name or "").strip().lower()
    for canonical, aliases in MARKER_ALIASES.items():
        if n in aliases or any(a in n for a in aliases):
            return canonical
    return n


def get_latest_marker(memory: MikhailSessionMemory, marker_name: str) -> Optional[LabRecord]:
    """Последняя запись по маркеру (по дате или порядку)."""
    if not memory or not memory.labs:
        return None
    canonical = _normalize_marker_name(marker_name)
    candidates = []
    for lab in memory.labs:
        mn = _normalize_marker_name(lab.marker_name)
        if mn == canonical or (canonical in mn or mn in canonical):
            candidates.append(lab)
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x.date or "", x.source_file or ""), reverse=True)
    return candidates[0]


def get_marker_history(memory: MikhailSessionMemory, marker_name: str) -> List[LabRecord]:
    """Все записи по маркеру, от старых к новым."""
    if not memory or not memory.labs:
        return []
    canonical = _normalize_marker_name(marker_name)
    out = []
    for lab in memory.labs:
        mn = _normalize_marker_name(lab.marker_name)
        if mn == canonical or (canonical in mn or mn in canonical):
            out.append(lab)
    out.sort(key=lambda x: (x.date or "", x.source_file or ""))
    return out


def compare_last_two(memory: MikhailSessionMemory, marker_name: str) -> Dict[str, Any]:
    """
    Сравнить два последних значения по маркеру.
    Возвращает: trend (improving | worsening | unchanged), first, last, delta.
    """
    history = get_marker_history(memory, marker_name)
    if len(history) < 2:
        return {"trend": "unknown", "first": None, "last": None, "delta": None}
    first = history[-2]
    last = history[-1]
    v1 = first.value
    v2 = last.value
    if v1 is None or v2 is None:
        return {"trend": "unknown", "first": v1, "last": v2, "delta": None}
    delta = v2 - v1
    canonical = _normalize_marker_name(marker_name)
    # Для гемоглобина, MCH, ферритина — выше лучше
    higher_better = canonical in ("hemoglobin", "mch", "ferritin", "free_t4")
    # Для TSH при гипотиреозе — снижение лучше; для эозинофилов — снижение лучше
    lower_better = canonical in ("tsh", "eosinophils", "wbc") or "лейкоцит" in (first.marker_name or "").lower()
    if abs(delta) < 1e-6:
        trend = "unchanged"
    elif higher_better:
        trend = "improving" if delta > 0 else "worsening"
    elif lower_better:
        trend = "improving" if delta < 0 else "worsening"
    else:
        trend = "unchanged" if abs(delta) < 1e-6 else ("improving" if delta > 0 else "worsening")
    return {
        "trend": trend,
        "first": v1,
        "last": v2,
        "delta": round(delta, 4),
        "first_date": first.date,
        "last_date": last.date,
    }


def summarize_trends(memory: MikhailSessionMemory) -> Dict[str, Any]:
    """Краткое суммари трендов по основным маркерам."""
    if not memory or not memory.labs:
        return {"markers": {}, "summary": []}
    markers_done = set()
    result = {}
    for canonical in list(MARKER_ALIASES.keys()):
        history = get_marker_history(memory, canonical)
        if len(history) < 2:
            continue
        cmp = compare_last_two(memory, history[0].marker_name if history else canonical)
        if cmp.get("trend") != "unknown":
            result[canonical] = cmp
            markers_done.add(canonical)
    summary = []
    for k, v in result.items():
        trend = v.get("trend")
        if trend == "improving":
            summary.append(f"{k}: улучшение")
        elif trend == "worsening":
            summary.append(f"{k}: ухудшение")
    return {"markers": result, "summary": summary}
