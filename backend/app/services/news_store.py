from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[2]
_NEWS_DATA_PATH = _ROOT / "data" / "news_data.json"


def _read_data() -> dict[str, Any]:
    if not _NEWS_DATA_PATH.exists():
        return {"items": []}
    try:
        raw = json.loads(_NEWS_DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    items = raw.get("items") if isinstance(raw.get("items"), list) else []
    return {"items": [x for x in items if isinstance(x, dict)]}


def _write_data(data: dict[str, Any]) -> None:
    _NEWS_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _NEWS_DATA_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_NEWS_DATA_PATH)


def list_news_items(*, limit: int = 500) -> list[dict[str, Any]]:
    data = _read_data()
    items = [dict(x) for x in (data.get("items") or []) if isinstance(x, dict)]
    items.sort(key=lambda x: float(x.get("updated_at_ts") or x.get("created_at_ts") or 0), reverse=True)
    return items[: max(1, min(int(limit or 500), 2000))]


def get_news_item(news_id: str) -> Optional[dict[str, Any]]:
    key = str(news_id or "").strip()
    if not key:
        return None
    for row in _read_data().get("items") or []:
        if str(row.get("id") or "").strip() == key:
            return dict(row)
    return None


def upsert_news_item(
    *,
    news_id: Optional[str],
    title: str,
    category: str,
    summary: str,
    content: str = "",
    tags: Optional[list[str]] = None,
    published_at: str = "",
    source_url: str = "",
    source_name: str = "",
    updated_by: str = "",
) -> dict[str, Any]:
    data = _read_data()
    now_ts = round(time.time(), 2)
    key = str(news_id or "").strip() or ("news-custom-" + str(uuid.uuid4()))
    clean_tags = []
    for t in (tags or []):
        txt = str(t or "").strip()
        if not txt:
            continue
        low = txt.lower()
        if any(low == str(x).lower() for x in clean_tags):
            continue
        clean_tags.append(txt[:50])
        if len(clean_tags) >= 20:
            break
    next_row = {
        "id": key,
        "title": str(title or "").strip()[:220],
        "category": str(category or "Новости").strip()[:120],
        "summary": str(summary or "").strip()[:1200],
        "content": str(content or "").strip()[:20000],
        "tags": clean_tags,
        "published_at": str(published_at or "").strip()[:32],
        "source_url": str(source_url or "").strip()[:1000],
        "source_name": str(source_name or "").strip()[:180],
        "is_custom": True,
        "updated_by": str(updated_by or "").strip()[:120],
        "updated_at_ts": now_ts,
    }
    rows = [x for x in (data.get("items") or []) if isinstance(x, dict)]
    idx = -1
    for i, row in enumerate(rows):
        if str(row.get("id") or "").strip() == key:
            idx = i
            break
    if idx >= 0:
        prev = rows[idx]
        next_row["created_at_ts"] = float(prev.get("created_at_ts") or now_ts)
        rows[idx] = next_row
    else:
        next_row["created_at_ts"] = now_ts
        rows.append(next_row)
    data["items"] = rows
    _write_data(data)
    return next_row


def delete_news_item(news_id: str) -> bool:
    key = str(news_id or "").strip()
    if not key:
        return False
    data = _read_data()
    rows = [x for x in (data.get("items") or []) if isinstance(x, dict)]
    next_rows = [x for x in rows if str(x.get("id") or "").strip() != key]
    if len(next_rows) == len(rows):
        now_ts = round(time.time(), 2)
        next_rows.append(
            {
                "id": key,
                "title": "",
                "category": "",
                "summary": "",
                "content": "",
                "tags": [],
                "published_at": "",
                "is_custom": True,
                "deleted": True,
                "updated_at_ts": now_ts,
                "created_at_ts": now_ts,
            }
        )
    data["items"] = next_rows
    _write_data(data)
    return True
