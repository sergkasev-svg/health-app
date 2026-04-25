"""
Сводка для админов: очереди enrichment, flywheel, слияние в chunks, флаги окружения.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.services.knowledge_enrichment_queue import RESULTS_FILE as _ENR_RESULTS, _QUEUE_FILE as _ENR_JOBS
from app.services.knowledge_flywheel import get_learning_queue_stats
from app.services.knowledge_index_merge import _MERGED_IDS_FILE
from app.services.medical_knowledge_indexer import CHUNKS_FILE, load_chunks
from app.services.task_queue import get_registry


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_knowledge_pipeline_overview() -> dict[str, Any]:
    flywheel = get_learning_queue_stats()
    jobs = list(_read_json(_ENR_JOBS).get("items") or [])
    results = list(_read_json(_ENR_RESULTS).get("items") or [])

    def _jstatus(j: dict) -> str:
        return str(j.get("status") or "").strip().lower()

    pending_jobs = sum(1 for j in jobs if _jstatus(j) == "pending")
    indexed_jobs = sum(1 for j in jobs if _jstatus(j) == "indexed")

    pending_review = sum(
        1
        for r in results
        if str(r.get("promotion_status") or "").strip().lower() in ("", "pending_review")
    )
    promoted = sum(
        1 for r in results if str(r.get("promotion_status") or "").strip().lower() == "promoted_to_flywheel"
    )

    chunks = list(load_chunks() or [])
    fw_chunks = sum(1 for c in chunks if str(c.get("source") or "") == "flywheel_approved")

    merge_meta: dict[str, Any] = {}
    merged_n = 0
    if _MERGED_IDS_FILE.exists():
        try:
            merge_meta = json.loads(_MERGED_IDS_FILE.read_text(encoding="utf-8"))
            merged_n = len(list(merge_meta.get("merged_flywheel_ids") or []))
        except Exception:
            merge_meta = {}

    reg = get_registry()
    task_names = sorted(reg.keys())

    return {
        "flywheel_queue": flywheel,
        "enrichment": {
            "jobs_total": len(jobs),
            "jobs_pending": pending_jobs,
            "jobs_indexed": indexed_jobs,
            "results_total": len(results),
            "results_pending_review": pending_review,
            "results_promoted_to_flywheel": promoted,
        },
        "keyword_index": {
            "chunks_total": len(chunks),
            "chunks_from_flywheel_approved": fw_chunks,
            "chunks_file_exists": CHUNKS_FILE.exists(),
        },
        "flywheel_chunk_merge": {
            "merged_flywheel_ids_count": merged_n,
            "state_updated_at": merge_meta.get("updated_at"),
        },
        "background_tasks_registered": task_names,
        "env_hints": {
            "pubmed_hints_disabled": os.environ.get("PUBMED_HINTS_DISABLED", "").strip().lower()
            in ("1", "true", "yes"),
            "push_webhook_configured": bool(os.environ.get("INTERNAL_PUSH_WEBHOOK_URL", "").strip()),
            "auto_merge_on_flywheel_approve_disabled": os.environ.get(
                "DISABLE_AUTO_MERGE_ON_FLYWHEEL_APPROVE", ""
            ).strip().lower()
            in ("1", "true", "yes"),
            "ncbi_api_key_set": bool(os.environ.get("NCBI_API_KEY", "").strip()),
        },
    }
