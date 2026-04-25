from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ROOT = _PROJECT_ROOT / "medical_knowledge" / "reasoning_graph"
_SYMPTOMS_FILE = _ROOT / "symptoms.json"
_CONDITIONS_FILE = _ROOT / "conditions.json"
_LABS_FILE = _ROOT / "labs.json"
_RED_FLAGS_FILE = _ROOT / "red_flags.json"
_FOODS_FILE = _ROOT / "foods.json"
_EDGES_FILE = _ROOT / "edges.json"
_FOLLOWUPS_FILE = _ROOT / "follow_up_questions.json"


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return fallback


@lru_cache(maxsize=1)
def _symptoms() -> list[dict[str, Any]]:
    payload = _read_json(_SYMPTOMS_FILE, [])
    return payload if isinstance(payload, list) else []


@lru_cache(maxsize=1)
def _conditions() -> list[dict[str, Any]]:
    payload = _read_json(_CONDITIONS_FILE, [])
    return payload if isinstance(payload, list) else []


@lru_cache(maxsize=1)
def _labs() -> list[dict[str, Any]]:
    payload = _read_json(_LABS_FILE, [])
    return payload if isinstance(payload, list) else []


@lru_cache(maxsize=1)
def _red_flags() -> list[dict[str, Any]]:
    payload = _read_json(_RED_FLAGS_FILE, [])
    return payload if isinstance(payload, list) else []


@lru_cache(maxsize=1)
def _foods() -> list[dict[str, Any]]:
    payload = _read_json(_FOODS_FILE, [])
    return payload if isinstance(payload, list) else []


@lru_cache(maxsize=1)
def _edges() -> list[dict[str, Any]]:
    payload = _read_json(_EDGES_FILE, [])
    return payload if isinstance(payload, list) else []


@lru_cache(maxsize=1)
def _followups() -> list[dict[str, Any]]:
    payload = _read_json(_FOLLOWUPS_FILE, [])
    return payload if isinstance(payload, list) else []


def _contains(text_low: str, phrase: str) -> bool:
    p = str(phrase or "").strip().lower()
    if len(p) < 2:
        return False
    if re.search(r"[а-яё]", p, flags=re.IGNORECASE):
        if p in text_low:
            return True
        if len(p) >= 4 and p[:-1] in text_low:
            return True
        return bool(re.search(rf"{re.escape(p)}[а-яё]*", text_low, flags=re.IGNORECASE))
    return bool(re.search(rf"(?<!\w){re.escape(p)}(?!\w)", text_low, flags=re.IGNORECASE))


def _dedup(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in values:
        s = str(x or "").strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out


def build_reasoning_graph_context(user_text: str, document_text: str = "") -> dict[str, Any]:
    merged = (str(user_text or "") + "\n" + str(document_text or "")).strip()
    text_low = merged.lower()
    if not text_low:
        return {}

    symptom_hits: list[dict[str, Any]] = []
    symptom_ids: set[str] = set()
    for s in _symptoms():
        sid = str(s.get("id") or "").strip()
        aliases = [str(x).strip() for x in (s.get("aliases") or []) if str(x).strip()]
        if not sid or not aliases:
            continue
        if any(_contains(text_low, a) for a in aliases):
            symptom_hits.append({"id": sid, "name": str(s.get("name") or sid), "default_questions": s.get("default_questions") or []})
            symptom_ids.add(sid)

    food_hits: list[dict[str, Any]] = []
    food_ids: set[str] = set()
    food_condition_boosts: set[str] = set()
    for f in _foods():
        fid = str(f.get("id") or "").strip()
        aliases = [str(x).strip() for x in (f.get("aliases") or []) if str(x).strip()]
        if not fid or not aliases:
            continue
        if any(_contains(text_low, a) for a in aliases):
            food_hits.append(
                {
                    "name": aliases[0],
                    "compound_hints": [str(x).strip() for x in (f.get("compound_hints") or []) if str(x).strip()],
                    "candidate_conditions": [str(x).strip() for x in (f.get("candidate_conditions") or []) if str(x).strip()],
                }
            )
            food_ids.add(fid)
            food_condition_boosts.update([str(x).strip() for x in (f.get("candidate_conditions") or []) if str(x).strip()])

    red_flag_hits: list[dict[str, Any]] = []
    for rf in _red_flags():
        rf_symptom = str(rf.get("symptom_id") or "").strip()
        triggers = [str(x).strip() for x in (rf.get("triggers") or []) if str(x).strip()]
        if rf_symptom and symptom_ids and rf_symptom not in symptom_ids:
            continue
        if any(_contains(text_low, t) for t in triggers):
            red_flag_hits.append(
                {
                    "title": str(rf.get("title") or "").strip(),
                    "action": str(rf.get("action") or "").strip(),
                    "matched_triggers": [t for t in triggers if _contains(text_low, t)],
                }
            )

    cond_by_id: dict[str, dict[str, Any]] = {}
    for c in _conditions():
        cid = str(c.get("id") or "").strip()
        if cid:
            cond_by_id[cid] = c

    scores: dict[str, float] = {}
    for e in _edges():
        sid = str(e.get("symptom_id") or "").strip()
        cid = str(e.get("condition_id") or "").strip()
        if sid and cid and sid in symptom_ids:
            scores[cid] = max(scores.get(cid, 0.0), float(e.get("weight") or 0.0))
    for cid in food_condition_boosts:
        scores[cid] = max(scores.get(cid, 0.0), scores.get(cid, 0.0) + 0.18)

    ranked_conditions: list[dict[str, Any]] = []
    for cid, sc in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        c = cond_by_id.get(cid) or {}
        label = str(c.get("name") or "").strip() or cid.replace("_", " ")
        ranked_conditions.append({"label": label, "confidence": round(min(0.92, max(0.35, sc)), 2), "condition_id": cid})

    lab_suggestions: list[str] = []
    top_condition_ids = {str(x.get("condition_id") or "").strip() for x in ranked_conditions[:4]}
    for row in _labs():
        sid = str(row.get("symptom_id") or "").strip()
        cid = str(row.get("condition_id") or "").strip()
        if sid and sid not in symptom_ids and cid and cid not in top_condition_ids:
            continue
        lab_suggestions.extend([str(x).strip() for x in (row.get("suggestions") or []) if str(x).strip()])

    followup: list[str] = []
    for s in symptom_hits:
        followup.extend([str(x).strip() for x in (s.get("default_questions") or []) if str(x).strip()])
    for row in _followups():
        scope = str(row.get("scope") or "").strip().lower()
        target_id = str(row.get("target_id") or "").strip()
        questions = [str(x).strip() for x in (row.get("questions") or []) if str(x).strip()]
        if not questions:
            continue
        if scope == "symptom" and target_id in symptom_ids:
            followup.extend(questions)
        elif scope == "food" and target_id in food_ids:
            followup.extend(questions)
        elif scope == "condition" and target_id in top_condition_ids:
            followup.extend(questions)

    # GI-priority for kefir/beans/gas case.
    if any(k in text_low for k in ("кефир", "фасол", "бобов")) and any(k in text_low for k in ("газ", "вздут", "пуч", "урчит")):
        gi = [
            "Есть ли боль в животе или только газы?",
            "Есть ли понос или запор?",
            "Становится ли хуже после фасоли/бобовых?",
            "Появляются ли газы или урчание после кефира в течение дня?",
        ]
        followup = gi + followup

    return {
        "matched_symptoms": symptom_hits,
        "matched_foods": food_hits,
        "candidate_conditions": ranked_conditions[:6],
        "lab_suggestions": _dedup(lab_suggestions)[:6],
        "red_flag_matches": red_flag_hits,
        "adaptive_questions": _dedup(followup)[:6],
        "priority_note": "red flags -> complaint-first -> food triggers -> candidate conditions -> lab suggestions -> short answer",
    }

