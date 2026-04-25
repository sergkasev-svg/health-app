from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ROOT = _PROJECT_ROOT / "medical_knowledge" / "symptom_severity"
_SYMPTOMS_DIR = _ROOT / "symptoms"
_RED_FLAGS_FILE = _ROOT / "red_flags" / "red_flags.json"
_RULES_FILE = _ROOT / "rules" / "graph_rules.json"
_RAG_FILE = _ROOT / "rag" / "symptom_severity_chunks.jsonl"


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
def _load_red_flags() -> list[dict[str, Any]]:
    payload = _load_json(_RED_FLAGS_FILE, [])
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
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= max_items:
            break
    return out


def _match_symptoms(text: str) -> list[str]:
    low = (text or "").lower()
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
    return _dedup(out, max_items=5)


def _infer_severity(text: str) -> str:
    low = (text or "").lower()
    m = re.search(r"\b([0-9]|10)\s*[/\\]\s*10\b", low)
    if m:
        v = int(m.group(1))
        if v >= 7:
            return "severe"
        if v >= 4:
            return "moderate"
        return "mild"
    if any(k in low for k in ("очень сильн", "нестерп", "самая сильная", "сильная боль", "задыхаюсь", "потеря сознания")):
        return "severe"
    if any(k in low for k in ("умерен", "мешает", "значительно")):
        return "moderate"
    return "mild"


def _red_flag_matches(text: str, matched_symptoms: list[str]) -> list[dict[str, str]]:
    low = (text or "").lower()
    symptom_set = set(matched_symptoms or [])
    out: list[dict[str, str]] = []
    for rf in _load_red_flags():
        symptom_id = str(rf.get("symptom") or "").strip().lower()
        if symptom_set and symptom_id and symptom_id not in symptom_set:
            continue
        triggers = [str(x).strip().lower() for x in (rf.get("triggers") or []) if str(x).strip()]
        if not triggers:
            continue
        if any(t in low for t in triggers):
            out.append(
                {
                    "id": str(rf.get("id") or "").strip(),
                    "title": str(rf.get("title") or "").strip(),
                    "action": str(rf.get("action") or "").strip(),
                }
            )
    return out


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


def build_symptom_severity_context(user_text: str, document_text: str = "") -> dict[str, Any]:
    merged = ((user_text or "") + "\n" + (document_text or "")).strip()
    matched_symptoms = _match_symptoms(merged)
    severity = _infer_severity(merged)
    red_flags = _red_flag_matches(merged, matched_symptoms)
    rules = _load_rules()

    followups: list[str] = []
    for sid in matched_symptoms:
        item = _load_symptoms().get(sid) or {}
        followups.extend([str(x).strip() for x in (item.get("severity_questions") or []) if str(x).strip()])

    urgent = bool(red_flags)
    route = "urgent" if urgent else ("doctor_soon" if severity in ("moderate", "severe") else "self_care_or_doctor_soon")
    return {
        "matched_symptoms": matched_symptoms,
        "severity": severity,
        "urgent": urgent,
        "route": route,
        "red_flag_matches": red_flags,
        "followup_questions": _dedup(followups, max_items=1),  # one key question per step
        "voice_concierge_rules": [str(x).strip() for x in (rules.get("voice_concierge_rules") or []) if str(x).strip()],
        "analysis_report_rules": [str(x).strip() for x in (rules.get("analysis_report_rules") or []) if str(x).strip()],
        "priority_note": "clinical_guidelines > ontologies > disease_clinical_profiles > symptom_severity",
        "rag_hits": _rag_hits(merged, top_k=3),
    }
