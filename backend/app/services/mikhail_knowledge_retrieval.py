"""
Широкий recall по нескольким базам знаний + отсев по лексической релевантности (ключи запроса)
и объединение ответов из разных семейств источников (round-robin), чтобы модель видела
не один доминирующий канал, а согласованный кросс-KB контекст.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.services.complaint_reference import search_complaint_reference
from app.services.integration_bridge import build_bridge_complaint_protocol
from app.services.medical_core_bridge import search_medical_core
from app.services.scenario_router import resolve_best_scenario
from app.services.scenario_pack_loader import load_all_scenario_packs

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_RAG_INDEX_FILE = _BACKEND_DIR / "app" / "knowledge" / "rag" / "mikhail_rag_index.jsonl"

# Минимум относительно лучшего скор — отсекаем «совсем мимо» после широкого recall.
_DEFAULT_REL_FLOOR = 0.18
# Абсолютный пол для очень коротких запросов (1–2 токена).
_ABS_FLOOR = 0.055


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-zа-яё0-9\-]+", _norm(text)) if len(t) >= 3}


def lexical_relevance_score(query: str, title: str, description: str) -> float:
    qt = _tokenize(query)
    if not qt:
        return 0.0
    blob = f"{title} {description}"
    dt = _tokenize(blob)
    if not dt:
        return 0.0
    inter = len(qt & dt)
    if inter <= 0:
        return 0.0
    base = inter / max(1, len(qt))
    tn = _norm(title)
    for t in qt:
        if t in tn:
            base += 0.12
    return min(base, 3.0)


def _source_bucket(source: str) -> str:
    s = (source or "").lower()
    if "clinical_engine" in s or "bridge" in s:
        return "A_bridge"
    if "complaints_reference" in s or s == "complaints_reference":
        return "B_complaints"
    if "medical_core" in s:
        return "C_medical_core"
    if "scenario_pack" in s:
        return "D_scenario"
    if "app_knowledge" in s:
        return "E_app_kb"
    return "F_rag_other"


def _recall_rag_index_rows(query: str, *, cap: int = 72) -> list[dict[str, Any]]:
    if not _RAG_INDEX_FILE.is_file():
        return []
    q_tokens = _tokenize(query)
    if not q_tokens:
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    try:
        with _RAG_INDEX_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                tokens = set(row.get("tokens") or [])
                if not tokens:
                    continue
                overlap = len(q_tokens & tokens)
                if overlap <= 0:
                    continue
                score = overlap / max(1, len(q_tokens))
                title = str(row.get("title") or "")
                if any(t in _norm(title) for t in q_tokens):
                    score += 0.65
                snippet = str(row.get("snippet") or row.get("text") or "")
                score = max(score, lexical_relevance_score(query, title, snippet))
                scored.append((score, row))
    except Exception:
        return []
    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sc, row in scored:
        key = _norm(str(row.get("title") or row.get("text") or ""))
        if not key or key in seen:
            continue
        seen.add(key)
        title = str(row.get("title") or "").strip()
        snippet = str(row.get("snippet") or row.get("text") or "").strip()[:520]
        out.append(
            {
                "title": title,
                "category": str(row.get("category") or "").strip(),
                "description": snippet,
                "source": str(row.get("source") or "rag").strip(),
                "_lex": float(sc),
            }
        )
        if len(out) >= cap:
            break
    return out


def _scenario_packs_lexical(query: str, *, top_k: int = 14) -> list[dict[str, Any]]:
    q_tokens = _tokenize(query)
    if not q_tokens:
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    for pack in load_all_scenario_packs():
        text_parts = [pack.id, pack.title_ru] + list(pack.chief_complaint_patterns or [])
        text_blob = " ".join(str(x or "") for x in text_parts)
        p_tokens = _tokenize(text_blob)
        if not p_tokens:
            continue
        overlap = len(q_tokens & p_tokens)
        if overlap <= 0:
            continue
        score = overlap / max(1, len(q_tokens))
        if _norm(query) in _norm(text_blob):
            score += 0.75
        scored.append(
            (
                score,
                {
                    "title": pack.title_ru or pack.id,
                    "category": pack.category or "",
                    "description": (
                        pack.chief_complaint_patterns[0]
                        if pack.chief_complaint_patterns
                        else (pack.title_ru or "")
                    ),
                    "source": f"scenario_pack:{pack.id}",
                    "_lex": float(score),
                },
            )
        )
    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored[:top_k]]


def _filter_by_lexical_floor(items: list[dict[str, Any]], query: str, *, rel_floor: float) -> list[dict[str, Any]]:
    for it in items:
        if "_lex" not in it or float(it.get("_lex") or 0) <= 0:
            it["_lex"] = lexical_relevance_score(
                query,
                str(it.get("title") or ""),
                str(it.get("description") or ""),
            )
    scored = [float(x.get("_lex") or 0) for x in items if float(x.get("_lex") or 0) > 0]
    if not scored:
        return []
    best = max(scored)
    floor = max(_ABS_FLOOR, best * rel_floor)
    return [x for x in items if float(x.get("_lex") or 0) >= floor]


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        key = _source_bucket(str(it.get("source") or "")) + "|" + _norm(str(it.get("title") or ""))
        if not _norm(str(it.get("title") or "")):
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _diversify_by_source_buckets(items: list[dict[str, Any]], final_n: int) -> list[dict[str, Any]]:
    """Когда релевантны несколько баз — по одному сильному хиту из каждого семейства, затем добор."""
    order = ["A_bridge", "B_complaints", "C_medical_core", "D_scenario", "E_app_kb", "F_rag_other"]
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for it in sorted(items, key=lambda x: float(x.get("_lex") or 0), reverse=True):
        buckets[_source_bucket(str(it.get("source") or ""))].append(it)
    picked: list[dict[str, Any]] = []
    idx = 0
    while len(picked) < final_n:
        progressed = False
        for _ in range(len(order)):
            b = order[idx % len(order)]
            idx += 1
            if buckets[b]:
                picked.append(buckets[b].pop(0))
                progressed = True
                if len(picked) >= final_n:
                    break
        if not progressed:
            break
    rest: list[dict[str, Any]] = []
    for b in order:
        rest.extend(buckets[b])
    rest.sort(key=lambda x: float(x.get("_lex") or 0), reverse=True)
    for it in rest:
        if len(picked) >= final_n:
            break
        picked.append(it)
    return picked[:final_n]


def unified_knowledge_search(
    query: str,
    *,
    final_items: int = 12,
    rel_floor: float = _DEFAULT_REL_FLOOR,
) -> dict[str, Any]:
    q = str(query or "").strip()
    raw: list[dict[str, Any]] = []

    for row in search_complaint_reference(q, top_k=max(14, final_items + 4)):
        if isinstance(row, dict):
            raw.append(
                {
                    "title": str(row.get("complaint") or row.get("name") or "").strip(),
                    "category": str(row.get("category") or "").strip(),
                    "description": str(row.get("description") or row.get("reason") or "").strip(),
                    "source": "complaints_reference",
                }
            )

    bridge = build_bridge_complaint_protocol(q, top_k=4)
    if isinstance(bridge, dict) and (bridge.get("complaint") or bridge.get("name")):
        raw.append(
            {
                "title": str(bridge.get("complaint") or bridge.get("name") or "").strip(),
                "category": str(bridge.get("category") or "").strip(),
                "description": str(bridge.get("description") or "").strip(),
                "source": "clinical_engine_bridge",
            }
        )

    for row in search_medical_core(q, limit=max(14, final_items + 4)):
        if isinstance(row, dict):
            raw.append(
                {
                    "title": str(row.get("name") or "").strip(),
                    "category": str(row.get("category") or "").strip(),
                    "description": str(row.get("description") or "").strip(),
                    "source": "medical_core",
                }
            )

    for row in resolve_best_scenario(q, max_results=max(12, final_items + 2), min_score=0.28):
        if isinstance(row, dict):
            raw.append(
                {
                    "title": str(row.get("title_ru") or row.get("id") or "").strip(),
                    "category": str(row.get("category") or "").strip(),
                    "description": str(row.get("chief_complaint") or "").strip(),
                    "source": f"scenario_pack:{row.get('id') or ''}",
                }
            )

    raw.extend(_scenario_packs_lexical(q, top_k=14))
    raw.extend(_recall_rag_index_rows(q, cap=max(72, final_items * 6)))

    raw = _dedupe_items(raw)
    for it in raw:
        lex_title = lexical_relevance_score(q, str(it.get("title") or ""), str(it.get("description") or ""))
        lex_prev = float(it.get("_lex") or 0)
        it["_lex"] = max(lex_title, lex_prev)

    filtered = _filter_by_lexical_floor(raw, q, rel_floor=rel_floor)
    diversified = _diversify_by_source_buckets(filtered, final_n=max(final_items, 8))

    clean: list[dict[str, Any]] = []
    for it in diversified:
        clean.append(
            {
                "title": str(it.get("title") or "").strip(),
                "category": str(it.get("category") or "").strip(),
                "description": str(it.get("description") or "").strip()[:900],
                "source": str(it.get("source") or "").strip(),
                "relevance": round(float(it.get("_lex") or 0), 4),
            }
        )

    return {
        "query": q,
        "items": clean,
        "recall_raw_count": len(raw),
        "after_filter_count": len(filtered),
        "final_count": len(clean),
    }


def rag_index_snippets_for_tooling(query: str, *, top_k: int = 8) -> list[dict[str, Any]]:
    """Только строки из mikhail_rag_index.jsonl — для поля rag_hits в worker API (как раньше)."""
    rows = _recall_rag_index_rows(query, cap=max(36, top_k * 5))
    out: list[dict[str, Any]] = []
    for r in rows[:top_k]:
        out.append(
            {
                "title": str(r.get("title") or "").strip(),
                "category": str(r.get("category") or "").strip(),
                "source": str(r.get("source") or "rag").strip(),
                "snippet": str(r.get("description") or "").strip()[:420],
            }
        )
    return out


def format_unified_kb_prompt_section(
    query: str,
    *,
    final_items: int = 12,
    max_chars: int = 4800,
    rel_floor: float = _DEFAULT_REL_FLOOR,
) -> str:
    bundle = unified_knowledge_search(query, final_items=final_items, rel_floor=rel_floor)
    items = bundle.get("items") or []
    if not items:
        return ""
    lines: list[str] = [
        "[UNIFIED_KB — wide recall, lexical key filter, multi-source merge]",
        "Ниже фрагменты из разных подключённых баз (жалобы, medical_core, сценарии, RAG-jsonl). "
        "Игнорируй строки с низкой релевантностью к формулировке пользователя; при нескольких подходящих каналах "
        "синтезируй один связный клинически безопасный ответ, без противоречий и без копирования дословно.",
        f"(meta: recall={bundle.get('recall_raw_count')}, after_lex={bundle.get('after_filter_count')}, shown={bundle.get('final_count')})",
        "",
    ]
    for it in items:
        src = str(it.get("source") or "")
        title = str(it.get("title") or "")
        rel = it.get("relevance")
        body = str(it.get("description") or "").strip()
        chunk = f"- [{src}] rel={rel} {title}\n  {body}"
        lines.append(chunk)
    out = "\n".join(lines).strip()
    if len(out) > max_chars:
        out = out[: max_chars - 24].rstrip() + "\n…[unified_kb truncated]"
    return out
