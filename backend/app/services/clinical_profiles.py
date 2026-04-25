"""
Offline clinical profiles resolver for 350 diseases.
Used by concierge and lab reports for fast relevant answers.
"""
import json
import re
from pathlib import Path
from typing import Any

from app.services.complaint_priority import get_priority_context

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_PROFILES_FILE = _PROJECT_ROOT / "medical_knowledge" / "diseases" / "disease_clinical_profiles_350.json"

_CACHE: list[dict[str, Any]] | None = None


def _load_profiles() -> list[dict[str, Any]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    if not _PROFILES_FILE.exists():
        _CACHE = []
        return _CACHE
    try:
        payload = json.loads(_PROFILES_FILE.read_text(encoding="utf-8"))
    except Exception:
        _CACHE = []
        return _CACHE
    items = payload.get("items") if isinstance(payload, dict) else None
    _CACHE = [x for x in (items or []) if isinstance(x, dict)]
    return _CACHE


def get_all_clinical_profiles() -> list[dict[str, Any]]:
    """Public accessor for offline clinical profiles list."""
    return list(_load_profiles())


def _tokens(text: str) -> list[str]:
    s = re.sub(r"[^\w\sа-яёa-z0-9]", " ", (text or "").lower())
    words = []
    for w in s.split():
        if len(w) < 3:
            continue
        words.append(w)
    return words


def search_clinical_profiles(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    words = set(_tokens(query))
    if not words:
        return []
    rows = _load_profiles()
    if not rows:
        return []
    prio = get_priority_context(rows)
    disease_boosts = prio.get("disease_boosts") or {}
    top50_ids = set(prio.get("top50_ids") or [])
    kw_map = {str(x.get("word")): int(x.get("count") or 0) for x in (prio.get("top_keywords") or []) if isinstance(x, dict)}

    scored: list[tuple[float, dict[str, Any]]] = []
    for it in rows:
        name = str(it.get("name") or "")
        description = str(it.get("description") or "")
        category = str(it.get("category") or "")
        hay = " ".join(
            [
                name.lower(),
                description.lower(),
                category.lower(),
                " ".join((it.get("anamnesis") or [])),
                " ".join((it.get("diagnostics") or [])),
                " ".join((it.get("treatment") or [])),
                " ".join((it.get("medications_recommended") or [])),
            ]
        ).lower()
        hits = sum(1 for w in words if w in hay)
        if hits <= 0:
            continue
        name_hits = sum(1 for w in words if w in name.lower())
        query_kw_boost = 0.0
        for w in words:
            c = kw_map.get(w, 0)
            if c > 0:
                query_kw_boost += min(0.02 * c, 0.35)
        pid = it.get("id")
        pid_key = str(pid) if pid is not None else ""
        dynamic_boost = float(disease_boosts.get(pid_key) or 0.0)
        static_boost = 0.75 if isinstance(pid, int) and pid in top50_ids else 0.0
        score = hits + name_hits * 1.5 + query_kw_boost + dynamic_boost + static_boost
        scored.append((score, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in scored[: max(1, top_k)]]


def format_profiles_for_prompt(items: list[dict[str, Any]], max_chars: int = 1800) -> str:
    if not items:
        return ""
    lines: list[str] = []
    for it in items:
        lines.append(f"- {it.get('name') or ''} ({it.get('icd10') or ''})")
        dx = list(it.get("diagnostics") or [])[:2]
        tr = list(it.get("treatment") or [])[:2]
        meds = list(it.get("medications_recommended") or [])[:3]
        if dx:
            lines.append("  Диагностика: " + "; ".join(dx))
        if tr:
            lines.append("  Лечение: " + "; ".join(tr))
        if meds:
            lines.append("  Препараты: " + ", ".join(meds))
    text = "\n".join(lines).strip()
    return text[:max_chars]

