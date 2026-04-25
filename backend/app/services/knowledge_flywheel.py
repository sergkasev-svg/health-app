"""Capture reviewed consultation cases for offline knowledge growth."""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_QUALITY_DIR = _BACKEND_DIR / "data" / "quality"
_QUEUE_FILE = _QUALITY_DIR / "knowledge_flywheel_queue.json"


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


def _slim_provenance(provenance: dict[str, Any] | None) -> dict[str, Any] | None:
    """Компактные метаданные источника (аудит, дедуп), без PII."""
    if not isinstance(provenance, dict) or not provenance:
        return None
    out: dict[str, Any] = {}
    for key in (
        "source",
        "branch_id",
        "thread_id",
        "comment_id",
        "capture_kind",
        "enrichment_result_id",
        "enrichment_job_id",
        "subject_id",
    ):
        val = provenance.get(key)
        if val is None or val == "":
            continue
        out[key] = str(val).strip()[:200]
    return out or None


def _anonymize_text(text: str) -> str:
    s = str(text or "")
    s = re.sub(r"\b[\w.\-]+@[\w.\-]+\.\w+\b", "[email]", s)
    s = re.sub(r"\+?\d[\d\-\s()]{7,}\d", "[phone]", s)
    s = re.sub(r"\b\d{2}\.\d{2}\.\d{4}\b", "[date]", s)
    s = re.sub(r"\b\d{4,}\b", "[number]", s)
    return s.strip()


def capture_learning_candidate(
    *,
    user_id: str,
    question: str,
    response: str,
    structured: dict[str, Any] | None,
    orchestrator_state: dict[str, Any] | None,
    report: dict[str, Any] | None,
    response_source: str,
    llm_used: bool,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store a sanitized candidate for later human review and offline promotion."""
    data = _read_json(_QUEUE_FILE)
    items = list(data.get("items") or [])
    item = {
        "id": str(uuid.uuid4()),
        "created_at": round(time.time(), 2),
        "user_id_hash": str(user_id or "")[:12],
        "review_status": "pending",
        "response_source": str(response_source or ""),
        "llm_used": bool(llm_used),
        "question": _anonymize_text(question)[:1500],
        "response": _anonymize_text(response)[:4000],
        "chief_complaint": _anonymize_text(str((structured or {}).get("chief_complaint") or ""))[:500],
        "severity": str((structured or {}).get("severity") or ""),
        "top_hypotheses": list((structured or {}).get("top_hypotheses") or [])[:3],
        "recommended_labs": list((structured or {}).get("recommended_labs") or [])[:5],
        "care_plan_today": list((structured or {}).get("care_plan_today") or [])[:5],
        "when_urgent": list((structured or {}).get("when_urgent") or [])[:4],
        "protocol_source": str((orchestrator_state or {}).get("protocol_source") or ""),
        "complaint": _anonymize_text(str((orchestrator_state or {}).get("complaint") or ""))[:300],
        "nutrition": list((report or {}).get("nutrition") or [])[:4],
        "activity": list((report or {}).get("activity") or [])[:4],
        "report_summary": _anonymize_text(str((report or {}).get("user_summary") or ""))[:2000],
    }
    slim_prov = _slim_provenance(provenance)
    if slim_prov:
        item["provenance"] = slim_prov
    items.append(item)
    data["items"] = items[-1000:]
    _write_json(_QUEUE_FILE, data)
    return item


def list_learning_candidates(limit: int = 100) -> list[dict[str, Any]]:
    data = _read_json(_QUEUE_FILE)
    items = list(data.get("items") or [])
    return items[-max(1, int(limit)) :]


def get_learning_candidate(candidate_id: str) -> dict[str, Any] | None:
    data = _read_json(_QUEUE_FILE)
    items = list(data.get("items") or [])
    target = str(candidate_id or "").strip()
    if not target:
        return None
    for item in items:
        if str(item.get("id") or "") == target:
            return item
    return None


def update_learning_candidate_review(
    candidate_id: str,
    *,
    review_status: str,
    review_notes: str = "",
    reviewer: str = "",
) -> dict[str, Any] | None:
    status = str(review_status or "").strip().lower()
    if status not in {"pending", "approved", "rejected"}:
        raise ValueError("Invalid review_status")
    data = _read_json(_QUEUE_FILE)
    items = list(data.get("items") or [])
    target = str(candidate_id or "").strip()
    if not target:
        return None
    updated = None
    for idx, item in enumerate(items):
        if str(item.get("id") or "") != target:
            continue
        next_item = dict(item)
        next_item["review_status"] = status
        next_item["review_notes"] = str(review_notes or "").strip()[:4000]
        next_item["reviewer"] = str(reviewer or "").strip()[:200]
        next_item["reviewed_at"] = round(time.time(), 2)
        items[idx] = next_item
        updated = next_item
        break
    if updated is None:
        return None
    data["items"] = items
    _write_json(_QUEUE_FILE, data)
    return updated


def get_learning_queue_stats() -> dict[str, int]:
    data = _read_json(_QUEUE_FILE)
    items = list(data.get("items") or [])
    stats = {"total": len(items), "pending": 0, "approved": 0, "rejected": 0}
    for item in items:
        status = str(item.get("review_status") or "pending").strip().lower()
        if status not in stats:
            continue
        stats[status] += 1
    return stats
