from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ROOT = _PROJECT_ROOT / "medical_knowledge" / "symptom_cause_graph"
_SYMPTOMS_DIR = _ROOT / "symptoms"
_CAUSES_DIR = _ROOT / "causes"
_EDGES_FILE = _ROOT / "edges" / "symptom_cause_edges.json"
_RULES_FILE = _ROOT / "rules" / "graph_rules.json"
_RAG_FILE = _ROOT / "rag" / "symptom_cause_chunks.jsonl"


def _load_json(path: Path, fallback: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return fallback


@lru_cache(maxsize=1)
def _load_symptoms() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not _SYMPTOMS_DIR.exists():
        return out
    for fp in sorted(_SYMPTOMS_DIR.glob("*.json")):
        item = _load_json(fp, {})
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or fp.stem).strip().lower()
        if sid:
            out[sid] = item
    return out


@lru_cache(maxsize=1)
def _load_causes() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not _CAUSES_DIR.exists():
        return out
    for fp in sorted(_CAUSES_DIR.glob("*.json")):
        item = _load_json(fp, {})
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or fp.stem).strip().lower()
        if cid:
            out[cid] = item
    return out


@lru_cache(maxsize=1)
def _load_edges() -> list[dict[str, Any]]:
    payload = _load_json(_EDGES_FILE, [])
    return payload if isinstance(payload, list) else []


@lru_cache(maxsize=1)
def _load_rules() -> dict[str, Any]:
    payload = _load_json(_RULES_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _load_rag_chunks() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not _RAG_FILE.exists():
        return out
    try:
        for line in _RAG_FILE.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s:
                continue
            item = json.loads(s)
            if isinstance(item, dict):
                out.append(item)
    except Exception:
        return []
    return out


def _dedup(items: list[str], max_items: int = 99) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in items:
        s = str(x or "").strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
        if len(out) >= max_items:
            break
    return out


def _detect_matched_symptoms(text: str) -> list[str]:
    low = (text or "").lower()
    if not low:
        return []
    out: list[str] = []
    for sid, item in _load_symptoms().items():
        aliases = [sid] + [str(x).strip().lower() for x in (item.get("aliases") or []) if str(x).strip()]
        for a in aliases:
            if len(a) < 3:
                continue
            if re.search(rf"(?<!\w){re.escape(a)}(?!\w)", low, flags=re.IGNORECASE) or (
                re.search(r"[а-яё]", a, flags=re.IGNORECASE) and a in low
            ):
                out.append(sid)
                break
    return _dedup(out, max_items=6)


def _is_after_food(text: str) -> bool:
    low = (text or "").lower()
    if not low:
        return False
    food_markers = ("после еды", "после", "после того", "после продукта", "после сыра", "после творога", "после молока")
    symptom_time = ("через", "спустя", "начинается", "появляется")
    return any(k in low for k in food_markers) and any(k in low for k in symptom_time + ("бол", "тошнот", "мигр", "голов"))


def _rag_hits(query: str, top_k: int = 3) -> list[str]:
    words = [w for w in re.sub(r"[^\w\sа-яёa-z0-9]", " ", (query or "").lower()).split() if len(w) > 2]
    if not words:
        return []
    scored: list[tuple[int, str]] = []
    for ch in _load_rag_chunks():
        text = str(ch.get("text") or "").strip()
        tags = " ".join([str(x).strip().lower() for x in (ch.get("tags") or []) if str(x).strip()])
        hay = (text + " " + tags).lower()
        score = sum(1 for w in words if w in hay)
        if score > 0 and text:
            scored.append((score, text))
    scored.sort(key=lambda x: x[0], reverse=True)
    return _dedup([t for _, t in scored], max_items=top_k)


def build_symptom_cause_context(
    user_text: str,
    document_text: str = "",
    food_trigger_context: dict[str, Any] | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    merged = ((user_text or "") + "\n" + (document_text or "")).strip()
    matched_symptoms = _detect_matched_symptoms(merged)
    if not matched_symptoms:
        return {}

    rules = _load_rules()
    edges = _load_edges()
    causes = _load_causes()
    after_food = _is_after_food(merged) or bool(food_trigger_context)

    edge_rows = [e for e in edges if str(e.get("symptom_id") or "").strip().lower() in set(matched_symptoms)]
    edge_rows.sort(key=lambda x: float(x.get("weight_hint") or 0.0), reverse=True)

    prioritized_ids: list[str] = []
    rule_questions: list[str] = []
    for rule in (rules.get("food_trigger_rules") or []):
        if not isinstance(rule, dict):
            continue
        rule_symptom = str(rule.get("if_symptom") or "").strip().lower()
        if rule_symptom not in matched_symptoms:
            continue
        if not after_food:
            continue
        prioritized_ids.extend([str(x).strip().lower() for x in (rule.get("prioritize_causes") or []) if str(x).strip()])
        rule_questions.extend([str(x).strip() for x in (rule.get("ask") or []) if str(x).strip()])

    differentials: list[dict[str, Any]] = []
    for e in edge_rows[: max(8, top_k * 2)]:
        cid = str(e.get("cause_id") or "").strip().lower()
        cause = causes.get(cid) or {}
        differentials.append(
            {
                "cause_id": cid,
                "label": str(cause.get("name") or cid).strip(),
                "weight_hint": float(e.get("weight_hint") or 0.0),
                "rationale": str(e.get("rationale") or "").strip(),
                "red_flag_pathway": bool(e.get("red_flag_pathway")),
            }
        )

    boosted = set(prioritized_ids)
    differentials.sort(
        key=lambda x: (
            0 if str(x.get("cause_id") or "").strip().lower() in boosted else 1,
            -(float(x.get("weight_hint") or 0.0)),
        )
    )

    candidate_labels = _dedup([str(x.get("label") or "").strip() for x in differentials], max_items=top_k)
    adaptive_questions: list[str] = []
    for sid in matched_symptoms:
        adaptive_questions.extend([str(x).strip() for x in ((_load_symptoms().get(sid) or {}).get("default_questions") or []) if str(x).strip()])
    adaptive_questions.extend(rule_questions)
    for d in differentials[:top_k]:
        # Use edge questions only after symptom-level defaults.
        edge_q = [str(x).strip() for x in (next((e.get("next_questions") for e in edge_rows if str(e.get("cause_id") or "").strip().lower() == str(d.get("cause_id") or "").strip().lower()), []) or []) if str(x).strip()]
        adaptive_questions.extend(edge_q[:1])

    return {
        "matched_symptoms": matched_symptoms,
        "candidate_hypotheses": candidate_labels,
        "differentials": differentials[:top_k],
        "adaptive_questions": _dedup(adaptive_questions, max_items=4),
        "priority_note": "clinical_guidelines > ontologies > disease_clinical_profiles > symptom_cause_graph",
        "question_priority": [str(x).strip() for x in (rules.get("question_priority") or []) if str(x).strip()],
        "food_trigger_rule_applied": bool(prioritized_ids),
        "rag_hits": _rag_hits(merged, top_k=3),
    }
