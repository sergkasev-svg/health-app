"""Backlog for weak complaints and improvement tasks."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_QUALITY_DIR = _BACKEND_DIR / "data" / "quality"
_BACKLOG_FILE = _QUALITY_DIR / "improvement_backlog.json"


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


def list_backlog(limit: int = 200) -> list[dict[str, Any]]:
    data = _read_json(_BACKLOG_FILE)
    return list(data.get("items") or [])[-max(1, int(limit)) :]


def add_backlog_item(
    *,
    complaint: str,
    cluster: str = "",
    reason: str = "",
    source: str = "analytics",
) -> dict[str, Any]:
    data = _read_json(_BACKLOG_FILE)
    items = list(data.get("items") or [])
    complaint_norm = str(complaint or "").strip().lower()
    for item in items:
        if str(item.get("complaint") or "").strip().lower() == complaint_norm and str(item.get("status") or "") != "done":
            return item
    row = {
        "id": str(uuid.uuid4()),
        "created_at": round(time.time(), 2),
        "complaint": str(complaint or "").strip()[:300],
        "cluster": str(cluster or "").strip()[:100],
        "reason": str(reason or "").strip()[:1000],
        "source": str(source or "analytics").strip(),
        "status": "open",
    }
    items.append(row)
    data["items"] = items[-1000:]
    _write_json(_BACKLOG_FILE, data)
    return row


def update_backlog_item(item_id: str, *, status: str, notes: str = "") -> dict[str, Any] | None:
    status = str(status or "").strip().lower()
    if status not in {"open", "in_progress", "done", "cancelled"}:
        raise ValueError("Invalid status")
    data = _read_json(_BACKLOG_FILE)
    items = list(data.get("items") or [])
    target = str(item_id or "").strip()
    if not target:
        return None
    for idx, item in enumerate(items):
        if str(item.get("id") or "") != target:
            continue
        next_item = dict(item)
        next_item["status"] = status
        next_item["notes"] = str(notes or "").strip()[:2000]
        next_item["updated_at"] = round(time.time(), 2)
        items[idx] = next_item
        data["items"] = items
        _write_json(_BACKLOG_FILE, data)
        return next_item
    return None


def backlog_stats() -> dict[str, int]:
    rows = list_backlog(limit=1000)
    stats = {"total": len(rows), "open": 0, "in_progress": 0, "done": 0, "cancelled": 0}
    for row in rows:
        st = str(row.get("status") or "open").strip().lower()
        if st in stats:
            stats[st] += 1
    return stats
