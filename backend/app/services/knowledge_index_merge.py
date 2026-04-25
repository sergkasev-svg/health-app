"""
Слияние одобренных кейсов knowledge flywheel в keyword-индекс (knowledge_cache/chunks.json).

Поток по плану: ревью в /review/learning-candidates → approve → периодический merge
(админ POST или фоновая задача knowledge_index_merge_flywheel).
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from app.services.knowledge_flywheel import list_learning_candidates
from app.services.medical_knowledge_indexer import CHUNKS_FILE, KNOWLEDGE_CACHE, load_chunks, store_chunks

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_QUALITY_DIR = _BACKEND_DIR / "data" / "quality"
_MERGED_IDS_FILE = _QUALITY_DIR / "knowledge_flywheel_chunks_merged.json"
_MAX_MERGED_IDS_TRACKED = 8000
_MAX_CHUNK_TEXT = 1800


def _read_state() -> set[str]:
    if not _MERGED_IDS_FILE.exists():
        return set()
    try:
        data = json.loads(_MERGED_IDS_FILE.read_text(encoding="utf-8"))
        ids = data.get("merged_flywheel_ids") or []
        return {str(x) for x in ids if x}
    except Exception:
        return set()


def _write_state(ids: set[str]) -> None:
    lst = sorted(ids)[-_MAX_MERGED_IDS_TRACKED:]
    _MERGED_IDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _MERGED_IDS_FILE.write_text(
        json.dumps({"merged_flywheel_ids": lst, "updated_at": round(time.time(), 2)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _flywheel_item_to_chunk(item: dict[str, Any]) -> dict[str, Any] | None:
    cid = str(item.get("id") or "").strip()
    if not cid:
        return None
    title = str(item.get("chief_complaint") or item.get("question") or "").strip()[:200]
    topic = str(item.get("complaint") or item.get("chief_complaint") or "").strip()[:200]
    parts = [
        str(item.get("question") or "").strip(),
        str(item.get("response") or "").strip(),
        str(item.get("report_summary") or "").strip(),
    ]
    text = "\n\n".join(p for p in parts if p).strip()
    text = re.sub(r"\s+", " ", text)[:_MAX_CHUNK_TEXT]
    if len(text) < 40:
        return None
    return {
        "id": f"fw-{cid}",
        "title": title or topic or "Клинический кейс",
        "topic": topic or title or "consultation",
        "text": text,
        "source": "flywheel_approved",
        "flywheel_candidate_id": cid,
        "merged_at": round(time.time(), 2),
    }


def merge_approved_flywheel_into_chunks(*, max_new: int = 25) -> dict[str, Any]:
    """
    Добавляет в chunks.json новые записи из review_status=approved, ещё не сливавшиеся.
    """
    cap = max(1, min(int(max_new or 25), 200))
    merged = _read_state()
    chunks = list(load_chunks() or [])
    existing_fw = {str(c.get("flywheel_candidate_id") or "") for c in chunks if c.get("flywheel_candidate_id")}
    # На случай старых записей только по id
    existing_ids = {str(c.get("id") or "") for c in chunks}

    candidates = list_learning_candidates(limit=5000)
    added = 0
    skipped = 0
    for item in candidates:
        if added >= cap:
            break
        if str(item.get("review_status") or "").strip().lower() != "approved":
            continue
        cid = str(item.get("id") or "").strip()
        if not cid or cid in merged or cid in existing_fw:
            skipped += 1
            continue
        fw_id = f"fw-{cid}"
        if fw_id in existing_ids:
            merged.add(cid)
            continue
        chunk = _flywheel_item_to_chunk(item)
        if not chunk:
            skipped += 1
            continue
        chunks.append(chunk)
        merged.add(cid)
        existing_ids.add(fw_id)
        added += 1

    KNOWLEDGE_CACHE.mkdir(parents=True, exist_ok=True)
    ok = store_chunks(chunks[-20000:]) if chunks else True
    if added:
        _write_state(merged)
    logger.info(
        "knowledge_index_merge_done",
        extra={"added": added, "skipped": skipped, "chunks_total": len(chunks), "stored": ok},
    )
    return {
        "ok": bool(ok),
        "added": added,
        "skipped": skipped,
        "chunks_total": len(chunks),
        "merged_ids_file": str(_MERGED_IDS_FILE),
    }
