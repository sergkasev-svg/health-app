"""Draft export/apply workflow for complaint enrichment."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_QUALITY_DIR = _BACKEND_DIR / "data" / "quality"
_DRAFTS_FILE = _QUALITY_DIR / "complaint_draft_candidates.json"
_COMPLAINTS_FILE = _PROJECT_ROOT / "medical_knowledge" / "diseases" / "complaints_reference.json"


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


def _merge_unique(base: list[str], extra: list[str], limit: int = 8) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in (base or []) + (extra or []):
        s = str(value or "").strip()
        if not s:
            continue
        low = s.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def list_draft_candidates(limit: int = 200, cluster: str = "") -> list[dict[str, Any]]:
    data = _read_json(_DRAFTS_FILE)
    items = list(data.get("items") or [])
    target_cluster = str(cluster or "").strip()
    if target_cluster:
        items = [x for x in items if str(x.get("cluster") or "").strip() == target_cluster]
    return items[-max(1, int(limit)) :]


def get_draft_candidate(draft_id: str) -> dict[str, Any] | None:
    rows = list_draft_candidates(limit=1000)
    target = str(draft_id or "").strip()
    if not target:
        return None
    for row in rows:
        if str(row.get("id") or "") == target:
            return row
    return None


def draft_stats() -> dict[str, int]:
    rows = list_draft_candidates(limit=1000)
    stats = {"total": len(rows), "pending": 0, "approved": 0, "applied": 0, "rejected": 0}
    for row in rows:
        st = str(row.get("status") or "pending").strip().lower()
        if st in stats:
            stats[st] += 1
    return stats


def create_draft_candidate(
    *,
    complaint: str,
    cluster: str = "",
    draft_entry: dict[str, Any] | None = None,
    source: str = "analytics",
    notes: str = "",
) -> dict[str, Any]:
    data = _read_json(_DRAFTS_FILE)
    items = list(data.get("items") or [])
    complaint_norm = str(complaint or "").strip().lower()
    for item in items:
        if str(item.get("complaint") or "").strip().lower() == complaint_norm and str(item.get("status") or "") not in {"applied", "rejected"}:
            return item
    row = {
        "id": str(uuid.uuid4()),
        "created_at": round(time.time(), 2),
        "complaint": str(complaint or "").strip()[:300],
        "cluster": str(cluster or "").strip()[:100],
        "source": str(source or "").strip()[:100],
        "notes": str(notes or "").strip()[:2000],
        "status": "pending",
        "draft_entry": draft_entry or {},
    }
    items.append(row)
    data["items"] = items[-1000:]
    _write_json(_DRAFTS_FILE, data)
    return row


def update_draft_candidate(draft_id: str, *, status: str, notes: str = "") -> dict[str, Any] | None:
    st = str(status or "").strip().lower()
    if st not in {"pending", "approved", "applied", "rejected"}:
        raise ValueError("Invalid status")
    data = _read_json(_DRAFTS_FILE)
    items = list(data.get("items") or [])
    target = str(draft_id or "").strip()
    if not target:
        return None
    for idx, item in enumerate(items):
        if str(item.get("id") or "") != target:
            continue
        next_item = dict(item)
        next_item["status"] = st
        if notes:
            next_item["notes"] = str(notes or "").strip()[:2000]
        next_item["updated_at"] = round(time.time(), 2)
        items[idx] = next_item
        data["items"] = items
        _write_json(_DRAFTS_FILE, data)
        return next_item
    return None


def apply_draft_candidate(draft_id: str) -> dict[str, Any] | None:
    drafts = _read_json(_DRAFTS_FILE)
    items = list(drafts.get("items") or [])
    target = next((x for x in items if str(x.get("id") or "") == str(draft_id or "").strip()), None)
    if not target:
        return None
    draft_entry = target.get("draft_entry") if isinstance(target.get("draft_entry"), dict) else {}
    complaint = str(target.get("complaint") or draft_entry.get("complaint") or "").strip()
    if not complaint:
        return None

    complaints_payload = _read_json(_COMPLAINTS_FILE)
    rows = list(complaints_payload.get("items") or [])
    applied_item = None
    for idx, row in enumerate(rows):
        if str(row.get("complaint") or "").strip().lower() != complaint.lower():
            continue
        updated = dict(row)
        for key in (
            "symptoms",
            "anamnesis_questions",
            "red_flags",
            "suggested_labs",
            "nutrition_recommendations",
            "physical_exercise_prevention_rehabilitation",
        ):
            updated[key] = _merge_unique(list(row.get(key) or []), list(draft_entry.get(key) or []))
        rows[idx] = updated
        applied_item = updated
        break
    if applied_item is None:
        applied_item = {
            "id": "draft_" + str(uuid.uuid4())[:8],
            "complaint": complaint,
            "category": str(draft_entry.get("category") or "Общая медицина"),
            "description": str(draft_entry.get("description") or "Черновая complaint-level запись после review."),
            "symptoms": _merge_unique([], list(draft_entry.get("symptoms") or [])),
            "anamnesis_questions": _merge_unique([], list(draft_entry.get("anamnesis_questions") or [])),
            "red_flags": _merge_unique([], list(draft_entry.get("red_flags") or []), limit=6),
            "suggested_labs": _merge_unique([], list(draft_entry.get("suggested_labs") or []), limit=6),
            "nutrition_recommendations": _merge_unique([], list(draft_entry.get("nutrition_recommendations") or []), limit=4),
            "physical_exercise_prevention_rehabilitation": _merge_unique([], list(draft_entry.get("physical_exercise_prevention_rehabilitation") or []), limit=4),
            "seasonality": draft_entry.get("seasonality") or {"peak_seasons": [], "year_round": True, "notes": "Требует уточнения сезонности."},
            "market_signal_cluster": str(target.get("cluster") or ""),
            "public_source_basis": ["draft_review_workflow"],
        }
        rows.append(applied_item)

    complaints_payload["items"] = rows
    complaints_payload["count"] = len(rows)
    _write_json(_COMPLAINTS_FILE, complaints_payload)
    update_draft_candidate(draft_id, status="applied")
    return applied_item


def get_draft_diff(draft_id: str) -> dict[str, Any] | None:
    target = get_draft_candidate(draft_id)
    if not target:
        return None
    draft_entry = target.get("draft_entry") if isinstance(target.get("draft_entry"), dict) else {}
    complaint = str(target.get("complaint") or draft_entry.get("complaint") or "").strip()
    complaints_payload = _read_json(_COMPLAINTS_FILE)
    rows = list(complaints_payload.get("items") or [])
    current = next((x for x in rows if str(x.get("complaint") or "").strip().lower() == complaint.lower()), {})
    diff: dict[str, Any] = {"complaint": complaint, "current_exists": bool(current), "fields": {}}
    for key in (
        "symptoms",
        "anamnesis_questions",
        "red_flags",
        "suggested_labs",
        "nutrition_recommendations",
        "physical_exercise_prevention_rehabilitation",
    ):
        current_items = list(current.get(key) or [])
        draft_items = list(draft_entry.get(key) or [])
        merged = _merge_unique(current_items, draft_items)
        current_norm = {str(x).strip().lower() for x in current_items}
        added = [x for x in merged if str(x).strip().lower() not in current_norm]
        diff["fields"][key] = {
            "current": current_items,
            "draft": draft_items,
            "added": added,
            "changed": bool(added),
        }
    return diff


def get_draft_diff(draft_id: str) -> dict[str, Any] | None:
    target = get_draft_candidate(draft_id)
    if not target:
        return None
    draft_entry = target.get("draft_entry") if isinstance(target.get("draft_entry"), dict) else {}
    complaint = str(target.get("complaint") or draft_entry.get("complaint") or "").strip()
    complaints_payload = _read_json(_COMPLAINTS_FILE)
    rows = list(complaints_payload.get("items") or [])
    current = next((x for x in rows if str(x.get("complaint") or "").strip().lower() == complaint.lower()), {})
    diff: dict[str, Any] = {"complaint": complaint, "current_exists": bool(current), "fields": {}}
    for key in (
        "symptoms",
        "anamnesis_questions",
        "red_flags",
        "suggested_labs",
        "nutrition_recommendations",
        "physical_exercise_prevention_rehabilitation",
    ):
        current_items = list(current.get(key) or [])
        draft_items = list(draft_entry.get(key) or [])
        merged = _merge_unique(current_items, draft_items)
        added = [x for x in merged if str(x).strip() and str(x).strip().lower() not in {str(y).strip().lower() for y in current_items}]
        diff["fields"][key] = {
            "current": current_items,
            "draft": draft_items,
            "added": added,
            "changed": bool(added),
        }
    return diff
