from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[2]
_FORUM_DATA_PATH = _ROOT / "data" / "forum_data.json"


def _read_data() -> dict[str, Any]:
    if not _FORUM_DATA_PATH.exists():
        return {"threads": [], "comments": []}
    try:
        raw = json.loads(_FORUM_DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    threads = raw.get("threads") if isinstance(raw.get("threads"), list) else []
    comments = raw.get("comments") if isinstance(raw.get("comments"), list) else []
    return {"threads": [x for x in threads if isinstance(x, dict)], "comments": [x for x in comments if isinstance(x, dict)]}


def _write_data(data: dict[str, Any]) -> None:
    _FORUM_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FORUM_DATA_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_FORUM_DATA_PATH)


def create_thread(
    *,
    branch_id: str,
    title: str,
    content: str,
    created_by_user_id: str,
    created_by_name: str = "",
    status: str = "approved",
) -> dict[str, Any]:
    data = _read_data()
    now = round(time.time(), 2)
    item = {
        "id": str(uuid.uuid4()),
        "branch_id": str(branch_id or "").strip(),
        "title": str(title or "").strip()[:180],
        "content": str(content or "").strip()[:5000],
        "status": str(status or "approved").strip().lower(),
        "created_by_user_id": str(created_by_user_id or "").strip(),
        "created_by_name": str(created_by_name or "").strip()[:120],
        "comments_count": 0,
        "last_activity_at": now,
        "created_at": now,
        "updated_at": now,
    }
    data["threads"].append(item)
    _write_data(data)
    return item


def list_threads(
    *,
    branch_id: str,
    limit: int = 100,
    viewer_user_id: str = "",
    include_hidden_for_moderator: bool = False,
) -> list[dict[str, Any]]:
    data = _read_data()
    items = []
    for row in data.get("threads") or []:
        if str(row.get("branch_id") or "") != str(branch_id or ""):
            continue
        status = str(row.get("status") or "approved").strip().lower()
        if status != "approved":
            if include_hidden_for_moderator:
                pass
            elif viewer_user_id and viewer_user_id == str(row.get("created_by_user_id") or ""):
                pass
            else:
                continue
        items.append(dict(row))
    items.sort(key=lambda x: float(x.get("last_activity_at") or x.get("created_at") or 0), reverse=True)
    return items[: max(1, min(int(limit or 100), 500))]


def get_thread(thread_id: str) -> Optional[dict[str, Any]]:
    key = str(thread_id or "").strip()
    if not key:
        return None
    data = _read_data()
    for row in data.get("threads") or []:
        if str(row.get("id") or "") == key:
            return dict(row)
    return None


def create_comment(
    *,
    thread_id: str,
    branch_id: str,
    content: str,
    created_by_user_id: str,
    created_by_name: str = "",
    status: str = "approved",
) -> dict[str, Any]:
    data = _read_data()
    now = round(time.time(), 2)
    item = {
        "id": str(uuid.uuid4()),
        "thread_id": str(thread_id or "").strip(),
        "branch_id": str(branch_id or "").strip(),
        "content": str(content or "").strip()[:5000],
        "status": str(status or "approved").strip().lower(),
        "created_by_user_id": str(created_by_user_id or "").strip(),
        "created_by_name": str(created_by_name or "").strip()[:120],
        "moderation_note": "",
        "moderated_by": "",
        "moderated_at": None,
        "created_at": now,
        "updated_at": now,
    }
    data["comments"].append(item)
    for idx, row in enumerate(data.get("threads") or []):
        if str(row.get("id") or "") == str(thread_id or ""):
            nxt = dict(row)
            nxt["comments_count"] = int(nxt.get("comments_count") or 0) + 1
            nxt["last_activity_at"] = now
            nxt["updated_at"] = now
            data["threads"][idx] = nxt
            break
    _write_data(data)
    return item


def list_comments(
    *,
    thread_id: str,
    limit: int = 300,
    viewer_user_id: str = "",
    include_hidden_for_moderator: bool = False,
) -> list[dict[str, Any]]:
    data = _read_data()
    items = []
    for row in data.get("comments") or []:
        if str(row.get("thread_id") or "") != str(thread_id or ""):
            continue
        status = str(row.get("status") or "approved").strip().lower()
        if status != "approved":
            if include_hidden_for_moderator:
                pass
            elif viewer_user_id and viewer_user_id == str(row.get("created_by_user_id") or ""):
                pass
            else:
                continue
        items.append(dict(row))
    items.sort(key=lambda x: float(x.get("created_at") or 0))
    return items[: max(1, min(int(limit or 300), 1000))]


def list_comments_for_moderation(*, status: str = "pending", branch_id: str = "", limit: int = 300) -> list[dict[str, Any]]:
    data = _read_data()
    wanted = str(status or "").strip().lower()
    items = []
    for row in data.get("comments") or []:
        if branch_id and str(row.get("branch_id") or "") != str(branch_id):
            continue
        row_status = str(row.get("status") or "approved").strip().lower()
        if wanted and row_status != wanted:
            continue
        items.append(dict(row))
    items.sort(key=lambda x: float(x.get("created_at") or 0), reverse=True)
    return items[: max(1, min(int(limit or 300), 1000))]


def get_comment(comment_id: str) -> Optional[dict[str, Any]]:
    key = str(comment_id or "").strip()
    if not key:
        return None
    data = _read_data()
    for row in data.get("comments") or []:
        if str(row.get("id") or "") == key:
            return dict(row)
    return None


def moderate_comment(
    *,
    comment_id: str,
    status: str,
    moderated_by: str,
    moderation_note: str = "",
) -> Optional[dict[str, Any]]:
    key = str(comment_id or "").strip()
    if not key:
        return None
    data = _read_data()
    now = round(time.time(), 2)
    for idx, row in enumerate(data.get("comments") or []):
        if str(row.get("id") or "") != key:
            continue
        nxt = dict(row)
        nxt["status"] = str(status or nxt.get("status") or "approved").strip().lower()
        nxt["moderated_by"] = str(moderated_by or "").strip()
        nxt["moderation_note"] = str(moderation_note or "").strip()[:500]
        nxt["moderated_at"] = now
        nxt["updated_at"] = now
        data["comments"][idx] = nxt
        _write_data(data)
        return nxt
    return None


def update_thread(*, thread_id: str, title: str, content: str) -> Optional[dict[str, Any]]:
    key = str(thread_id or "").strip()
    if not key:
        return None
    data = _read_data()
    now = round(time.time(), 2)
    for idx, row in enumerate(data.get("threads") or []):
        if str(row.get("id") or "") != key:
            continue
        nxt = dict(row)
        nxt["title"] = str(title or nxt.get("title") or "").strip()[:180]
        nxt["content"] = str(content or nxt.get("content") or "").strip()[:5000]
        nxt["updated_at"] = now
        nxt["last_activity_at"] = now
        data["threads"][idx] = nxt
        _write_data(data)
        return nxt
    return None


def delete_thread(*, thread_id: str) -> bool:
    key = str(thread_id or "").strip()
    if not key:
        return False
    data = _read_data()
    rows = [x for x in (data.get("threads") or []) if isinstance(x, dict)]
    next_rows = [x for x in rows if str(x.get("id") or "") != key]
    if len(next_rows) == len(rows):
        return False
    data["threads"] = next_rows
    data["comments"] = [x for x in (data.get("comments") or []) if str((x or {}).get("thread_id") or "") != key]
    _write_data(data)
    return True


def update_comment(*, comment_id: str, content: str) -> Optional[dict[str, Any]]:
    key = str(comment_id or "").strip()
    if not key:
        return None
    data = _read_data()
    now = round(time.time(), 2)
    thread_id = ""
    for idx, row in enumerate(data.get("comments") or []):
        if str(row.get("id") or "") != key:
            continue
        nxt = dict(row)
        nxt["content"] = str(content or "").strip()[:5000]
        nxt["updated_at"] = now
        data["comments"][idx] = nxt
        thread_id = str(nxt.get("thread_id") or "")
        break
    if not thread_id:
        return None
    for t_idx, row in enumerate(data.get("threads") or []):
        if str(row.get("id") or "") == thread_id:
            t_next = dict(row)
            t_next["last_activity_at"] = now
            t_next["updated_at"] = now
            data["threads"][t_idx] = t_next
            break
    _write_data(data)
    for row in data.get("comments") or []:
        if str(row.get("id") or "") == key:
            return dict(row)
    return None


def delete_comment(*, comment_id: str) -> bool:
    key = str(comment_id or "").strip()
    if not key:
        return False
    data = _read_data()
    comments = [x for x in (data.get("comments") or []) if isinstance(x, dict)]
    target = None
    for row in comments:
        if str(row.get("id") or "") == key:
            target = row
            break
    if not target:
        return False
    thread_id = str(target.get("thread_id") or "")
    data["comments"] = [x for x in comments if str(x.get("id") or "") != key]
    if thread_id:
        cnt = 0
        for row in data.get("comments") or []:
            if str((row or {}).get("thread_id") or "") == thread_id:
                cnt += 1
        now = round(time.time(), 2)
        for idx, row in enumerate(data.get("threads") or []):
            if str(row.get("id") or "") != thread_id:
                continue
            nxt = dict(row)
            nxt["comments_count"] = cnt
            nxt["last_activity_at"] = now
            nxt["updated_at"] = now
            data["threads"][idx] = nxt
            break
    _write_data(data)
    return True

