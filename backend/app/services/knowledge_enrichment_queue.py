"""
Очередь последующего обогащения знаний по теме консультации.

Синхронный ответ пользователю не ждёт завершения: задача ставится в task_queue
(в режиме sync выполняется сразу после ответа; позже — broker).

Сейчас: индексированный поиск (medical_knowledge_search) → PubMed E-utilities (см. pubmed_lite,
отключение PUBMED_HINTS_DISABLED=1, опционально NCBI_API_KEY) → правила verification (tier) →
снимок в JSON → при tier != rejected и реальном пользователе — in-app уведомление (user_store)
и опционально INTERNAL_PUSH_WEBHOOK_URL (push_delivery).

Фоновые задачи (task_queue): knowledge_enrichment_seed_batch, knowledge_enrichment_daily_clusters
(слабые жалобы/кластеры из get_runtime_overview), knowledge_index_merge_flywheel — см. соседние модули.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

from app.services.task_queue import enqueue_task
from app.services.user_store import get_chat_history, normalize_subject_id

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_QUALITY_DIR = _BACKEND_DIR / "data" / "quality"
_QUEUE_FILE = _QUALITY_DIR / "knowledge_enrichment_jobs.json"
RESULTS_FILE = _QUALITY_DIR / "knowledge_enrichment_results.json"
SEED_TOPICS_FILE = _QUALITY_DIR / "knowledge_refresh_seed_topics.txt"

_DEDUP_SECONDS = 3600
_MIN_TOPIC_LEN = 8
_SYSTEM_USER = "system_enrichment_batch"
_MIN_SUMMARY_FOR_OK = 80
_MIN_SUMMARY_REJECT = 28
_MIN_CLIN_FOR_REJECT = 28


def _verify_enrichment_rules(
    summary: str,
    facade: dict[str, Any],
    idx_out: dict[str, Any],
) -> dict[str, Any]:
    """
    Правила без LLM: достаточно ли текста для пользовательского уведомления / ревью.
    tier: ok | limited | rejected
    """
    summ = str(summary or "").strip()
    clin = str((facade or {}).get("clinical_simple_excerpt") or "").strip()
    has_rf = bool((facade or {}).get("indexed_has_red_flags"))
    idx_err = (facade or {}).get("error")
    reasons: list[str] = []
    tier = "ok"
    if len(summ) < _MIN_SUMMARY_REJECT and len(clin) < _MIN_CLIN_FOR_REJECT:
        reasons.append("thin_evidence")
        tier = "rejected"
    elif len(summ) < _MIN_SUMMARY_FOR_OK and len(clin) < 40:
        reasons.append("limited_context")
        tier = "limited"
    if idx_err and len(summ) < 24:
        reasons.append("resolver_error")
        if tier == "ok":
            tier = "limited"
    if has_rf:
        reasons.append("red_flags_in_indexed")
        if tier == "ok":
            tier = "limited"
    src_n = len(list((idx_out or {}).get("sources") or [])) if isinstance(idx_out, dict) else 0
    if src_n == 0 and len(summ) < 50 and len(clin) < 50:
        reasons.append("no_sources_and_short")
        if tier == "ok":
            tier = "limited"
    passed = tier != "rejected"
    return {
        "passed": passed,
        "tier": tier,
        "reasons": reasons,
        "checked_at": round(time.time(), 2),
    }


def _maybe_notify_enrichment_ready(job: dict[str, Any], row: dict[str, Any]) -> None:
    """In-app уведомление: только реальным пользователям, не seed/system, не при rejected."""
    uid = str(job.get("notify_user_id") or "").strip()
    if not uid or uid == _SYSTEM_USER:
        return
    ver = row.get("verification") if isinstance(row.get("verification"), dict) else {}
    if str(ver.get("tier") or "") == "rejected":
        return
    try:
        from app.services.user_store import add_notification
    except Exception as e:
        logger.debug("enrichment_notify_import_failed", extra={"error": str(e)})
        return
    topic = str(row.get("topic_preview") or "")[:200]
    rid = str(row.get("id") or "")
    summ = str(row.get("indexed_summary_excerpt") or "").strip()[:280]
    tier = str(ver.get("tier") or "")
    lines: list[str] = []
    if tier == "limited":
        lines.append("Краткий обзор по теме (материал ограничен).")
    reasons = list(ver.get("reasons") or [])
    if "red_flags_in_indexed" in reasons:
        lines.append("В справочных материалах упоминаются тревожные признаки — при необходимости обсудите с врачом.")
    lines.append(topic or "Ваша тема консультации")
    if summ:
        lines.append(summ)
    body = "\n".join(lines)
    action = {
        "type": "knowledge_enrichment",
        "result_id": rid,
        "subject_id": str(job.get("subject_id") or "main"),
        "topic_fingerprint": str(job.get("topic_fingerprint") or ""),
        "deep_link": f"#knowledge-enrichment={rid}",
    }
    item = add_notification(
        uid,
        "Обновление по вашей теме",
        body=body,
        unread=True,
        action=action,
    )
    try:
        from app.services.push_delivery import send_internal_push_webhook

        created = float((item or {}).get("created_at") or 0)
        if item and (time.time() - created) < 90:
            send_internal_push_webhook(
                user_id=uid,
                title="Обновление по вашей теме",
                body=body[:1200],
                action=action,
            )
    except Exception as e:
        logger.debug("enrichment_push_webhook_failed", extra={"error": str(e)[:120]})


def _slim_facade_context(topic: str) -> dict[str, Any]:
    """Офлайн+индекс+микробиом через существующий resolver (без новых сетевых вызовов)."""
    try:
        from app.services.knowledge_base_resolver import resolve_medical_context

        raw = resolve_medical_context(topic or "", language="ru")
        idx = raw.get("indexed") if isinstance(raw.get("indexed"), dict) else {}
        mb = raw.get("microbiome_context") if isinstance(raw.get("microbiome_context"), dict) else {}
        return {
            "intent": str(raw.get("intent") or "")[:80],
            "clinical_simple_excerpt": str(raw.get("clinical_simple") or "")[:500],
            "indexed_summary_excerpt": str(idx.get("summary") or "")[:600],
            "indexed_has_red_flags": bool(idx.get("red_flags")),
            "microbiome_active": bool(mb.get("active") or mb.get("hits")),
        }
    except Exception as e:
        logger.debug("facade_context_failed", extra={"error": str(e)})
        return {"error": str(e)[:200]}


def _online_hints_for_topic(topic: str) -> list[dict[str, str]]:
    """Ранжированные публичные справочники (уже используются в medical_knowledge_search при пустом индексе)."""
    try:
        from app.services.medical_knowledge_search import ONLINE_REFERENCE_LINKS
        from app.services.medical_source_ranker import detect_query_domain, rank_sources_for_domain

        domain = detect_query_domain(topic or "")
        ranked = rank_sources_for_domain(ONLINE_REFERENCE_LINKS, domain)[:8]
        return [{"url": str(u)[:500], "kind": "trusted_reference"} for u in ranked if u]
    except Exception as e:
        logger.debug("online_hints_failed", extra={"error": str(e)})
        return []


def list_enrichment_results(limit: int = 100) -> list[dict[str, Any]]:
    data = _read_json(RESULTS_FILE)
    items = list(data.get("items") or [])
    n = max(1, min(int(limit or 100), 500))
    return items[-n:]


def list_enrichment_jobs(limit: int = 100) -> list[dict[str, Any]]:
    data = _read_json(_QUEUE_FILE)
    items = list(data.get("items") or [])
    n = max(1, min(int(limit or 100), 500))
    return items[-n:]


def _chat_alignment_vs_topic_fingerprint(
    topic_fingerprint: str,
    *,
    user_id: str,
    subject_id: str,
    max_user_turns: int = 6,
) -> dict[str, Any]:
    """
    Сопоставление снимка обогащения с недавними репликами пользователя в чате профиля.
    """
    fp = str(topic_fingerprint or "").strip()
    sid = normalize_subject_id(subject_id)
    uid = str(user_id or "").strip()
    messages = get_chat_history(uid, subject_id=sid) if uid else []
    user_fps: list[str] = []
    last_user_snippet = ""
    for m in reversed(list(messages or [])):
        if str(m.get("role") or "") != "user":
            continue
        c = str(m.get("content") or "").strip()
        if len(c) < 8:
            continue
        if not last_user_snippet:
            last_user_snippet = c[:160]
        user_fps.append(_topic_fingerprint(c))
        if len(user_fps) >= max_user_turns:
            break
    exact = bool(fp and fp in user_fps)
    loose = False
    if fp and not exact:
        for ufp in user_fps:
            if not ufp:
                continue
            if fp in ufp or ufp in fp:
                loose = True
                break
    return {
        "matches_recent_user_turn": exact,
        "matches_recent_user_turn_loose": exact or loose,
        "compared_turns": len(user_fps),
        "last_user_message_preview": last_user_snippet or None,
    }


def get_enrichment_snapshot_for_user(
    result_id: str,
    *,
    user_id: str,
    subject_id: str | None,
) -> tuple[dict[str, Any] | None, str]:
    """
    Снимок для клиента: только владелец (user_hash[:24]) и совпадающий subject_id.
    Возвращает (payload, "") или (None, "not_found"|"forbidden").
    """
    rid = str(result_id or "").strip()
    if not rid:
        return None, "not_found"
    row = get_enrichment_result(rid)
    if not row:
        return None, "not_found"
    uid = str(user_id or "").strip()
    h = str(row.get("user_hash") or "")
    if str(uid)[:24] != h:
        return None, "forbidden"
    sid_req = normalize_subject_id(subject_id)
    sid_stored = normalize_subject_id(row.get("subject_id"))
    if sid_stored != sid_req:
        return None, "forbidden"
    snap = {k: v for k, v in row.items() if k != "user_hash"}
    tfp = str(row.get("topic_fingerprint") or "")
    alignment = _chat_alignment_vs_topic_fingerprint(tfp, user_id=uid, subject_id=sid_req)
    return (
        {
            "snapshot": snap,
            "chat_alignment": alignment,
        },
        "",
    )


def get_enrichment_result(result_id: str) -> dict[str, Any] | None:
    rid = str(result_id or "").strip()
    if not rid:
        return None
    data = _read_json(RESULTS_FILE)
    for it in reversed(list(data.get("items") or [])):
        if str(it.get("id") or "") == rid:
            return it
    return None


def update_enrichment_result_status(
    result_id: str,
    *,
    promotion_status: str,
    notes: str = "",
) -> dict[str, Any] | None:
    rid = str(result_id or "").strip()
    if not rid:
        return None
    data = _read_json(RESULTS_FILE)
    items = list(data.get("items") or [])
    updated = None
    for i, it in enumerate(items):
        if str(it.get("id") or "") == rid:
            next_row = dict(it)
            next_row["promotion_status"] = str(promotion_status or "")[:80]
            next_row["promotion_notes"] = str(notes or "")[:500]
            next_row["promotion_updated_at"] = round(time.time(), 2)
            items[i] = next_row
            updated = next_row
            break
    if not updated:
        return None
    data["items"] = items
    _write_json(RESULTS_FILE, data)
    return updated


def promote_enrichment_result_to_flywheel(result_id: str, *, reviewer: str = "") -> dict[str, Any]:
    """Копирует снимок в очередь knowledge_flywheel для человеческого ревью и индексации."""
    from app.services.knowledge_flywheel import capture_learning_candidate

    row = get_enrichment_result(result_id)
    if not row:
        raise ValueError("result_not_found")
    topic = str(row.get("topic_preview") or "").strip()
    if len(topic) < _MIN_TOPIC_LEN:
        raise ValueError("topic_too_short")
    facade = row.get("facade_context") if isinstance(row.get("facade_context"), dict) else {}
    parts = [
        str(row.get("indexed_summary_excerpt") or "").strip(),
        str(facade.get("clinical_simple_excerpt") or "").strip(),
    ]
    body = "\n\n".join(p for p in parts if p)[:4000]
    prov = {
        "source": "knowledge_enrichment_result",
        "enrichment_result_id": str(result_id)[:80],
        "enrichment_job_id": str(row.get("job_id") or "")[:80],
        "subject_id": str(row.get("subject_id") or "main")[:40],
    }
    item = capture_learning_candidate(
        user_id="enrichment_queue",
        question=topic[:1500],
        response=body or topic[:500],
        structured={
            "chief_complaint": topic[:500],
            "severity": "YELLOW",
            "top_hypotheses": [],
            "recommended_labs": [],
        },
        orchestrator_state={"protocol_source": "knowledge_enrichment", "complaint": topic[:300]},
        report={"user_summary": str(row.get("indexed_summary_excerpt") or "")[:2000]},
        response_source="knowledge_enrichment_promotion",
        llm_used=bool(row.get("llm_used_in_turn")),
        provenance=prov,
    )
    update_enrichment_result_status(
        result_id,
        promotion_status="promoted_to_flywheel",
        notes=reviewer or "promoted",
    )
    return {"flywheel_item": item, "result_id": result_id}


def run_seed_batch_enrichment(max_topics: int = 20) -> dict[str, Any]:
    """
    Фоновая задача: строки из knowledge_refresh_seed_topics.txt → постановка в очередь (system user).
    Файл опционален; не ломает приложение при отсутствии.
    """
    path = SEED_TOPICS_FILE
    if not path.exists():
        return {"ok": True, "skipped": True, "reason": "no_seed_file", "enqueued": 0}
    lines = []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    except Exception as e:
        return {"ok": False, "error": str(e), "enqueued": 0}
    cap = max(1, min(int(max_topics or 20), 100))
    enqueued = 0
    last: dict[str, Any] = {}
    for topic in lines[:cap]:
        last = enqueue_knowledge_enrichment_followup(
            user_id=_SYSTEM_USER,
            subject_id="main",
            topic=topic[:500],
            llm_used=False,
            response_source="seed_batch",
        )
        if last.get("queued"):
            enqueued += 1
    return {"ok": True, "enqueued": enqueued, "last": last, "topics_seen": min(len(lines), cap)}


def run_daily_cluster_enrichment_from_analytics(*, max_topics: int = 8) -> dict[str, Any]:
    """
    Раз в сутки (cron → task_queue): weak_complaints + слабые кластеры из runtime overview → очередь enrichment.
    """
    try:
        from app.services.runtime_analytics import get_runtime_overview
    except Exception as e:
        return {"ok": False, "error": str(e), "enqueued": 0}

    cap = max(1, min(int(max_topics or 8), 40))
    ov = get_runtime_overview(limit=2500)
    topics: list[str] = []
    seen: set[str] = set()

    def _add(t: str) -> None:
        s = str(t or "").strip()
        if len(s) < _MIN_TOPIC_LEN:
            return
        key = s[:120].lower()
        if key in seen:
            return
        seen.add(key)
        topics.append(s[:500])

    for row in list(ov.get("weak_complaints") or [])[: cap + 5]:
        _add(str(row.get("complaint") or ""))

    roadmap = list(ov.get("cluster_roadmap") or [])
    by_quality = sorted(
        roadmap,
        key=lambda x: float(x.get("avg_quality_score") or 100.0),
    )
    for cluster_block in by_quality[:4]:
        for wc in list(cluster_block.get("weakest_complaints") or [])[:4]:
            _add(str(wc or ""))
            if len(topics) >= cap + 8:
                break
        if len(topics) >= cap + 8:
            break

    enqueued = 0
    last: dict[str, Any] = {}
    for topic in topics[:cap]:
        last = enqueue_knowledge_enrichment_followup(
            user_id=_SYSTEM_USER,
            subject_id="main",
            topic=topic,
            llm_used=False,
            response_source="daily_cluster_analytics",
        )
        if last.get("queued"):
            enqueued += 1
    return {
        "ok": True,
        "enqueued": enqueued,
        "candidates": topics[:cap],
        "last_enqueue": last,
    }


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _topic_fingerprint(topic: str) -> str:
    s = re.sub(r"\s+", " ", (topic or "").strip().lower())[:120]
    return s[:80]


def enqueue_knowledge_enrichment_followup(
    *,
    user_id: str,
    subject_id: str | None,
    topic: str,
    llm_used: bool,
    response_source: str,
) -> dict[str, Any]:
    """
    Ставит задачу обогащения по теме (дедуп по пользователю/профилю/отпечатку темы за час).
    Возвращает {queued, job_id?, reason?}.
    """
    fp = _topic_fingerprint(topic)
    if len(fp) < _MIN_TOPIC_LEN:
        return {"queued": False, "reason": "topic_too_short"}

    data = _read_json(_QUEUE_FILE)
    items = list(data.get("items") or [])
    now = time.time()
    user_hash = str(user_id or "")[:24]
    sid = normalize_subject_id(subject_id)

    for it in reversed(items[-120:]):
        if it.get("user_hash") == user_hash and it.get("subject_id") == sid:
            if str(it.get("topic_fingerprint") or "") == fp:
                if now - float(it.get("created_at") or 0) < _DEDUP_SECONDS:
                    return {"queued": False, "reason": "deduped_recent"}

    job_id = str(uuid.uuid4())
    preview = re.sub(r"\s+", " ", (topic or "").strip())[:500]
    raw_uid = str(user_id or "").strip()
    notify_uid = raw_uid[:128] if raw_uid and raw_uid != _SYSTEM_USER else ""
    items.append(
        {
            "id": job_id,
            "created_at": round(now, 2),
            "user_hash": user_hash,
            "notify_user_id": notify_uid,
            "subject_id": sid,
            "topic_fingerprint": fp,
            "topic_preview": preview,
            "llm_used": bool(llm_used),
            "response_source": str(response_source or "")[:120],
            "status": "pending",
        }
    )
    data["items"] = items[-3000:]
    _write_json(_QUEUE_FILE, data)

    try:
        enqueue_task("knowledge_enrichment_followup", {"job_id": job_id})
    except Exception as e:
        logger.warning("knowledge_enrichment_enqueue_failed", extra={"error": str(e), "job_id": job_id})
        return {"queued": False, "reason": "enqueue_failed", "job_id": job_id}

    return {"queued": True, "job_id": job_id}


def _append_enrichment_result(row: dict[str, Any]) -> None:
    data = _read_json(RESULTS_FILE)
    lst = list(data.get("items") or [])
    lst.append(row)
    data["items"] = lst[-5000:]
    _write_json(RESULTS_FILE, data)


def process_knowledge_enrichment_job(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Обработчик task_queue: поиск по индексу, запись снимка для последующего ревью/промоушена в справочники.
    """
    job_id = str((payload or {}).get("job_id") or "").strip()
    if not job_id:
        return {"ok": False, "error": "missing_job_id"}

    data = _read_json(_QUEUE_FILE)
    items = list(data.get("items") or [])
    job = next((x for x in items if str(x.get("id") or "") == job_id), None)
    if not job:
        return {"ok": False, "error": "job_not_found"}

    topic = str(job.get("topic_preview") or "").strip()
    if len(topic) < _MIN_TOPIC_LEN:
        _mark_job(items, job_id, "skipped_short_topic")
        data["items"] = items
        _write_json(_QUEUE_FILE, data)
        return {"ok": True, "skipped": True}

    idx_out: dict[str, Any] = {}
    try:
        from app.services.medical_knowledge_search import search as med_search

        idx_out = med_search(topic, max_results=8, language="ru")
    except Exception as e:
        logger.warning("knowledge_enrichment_search_failed", extra={"error": str(e), "job_id": job_id})
        idx_out = {"summary": "", "sources": [], "error": str(e)}

    summary = str(idx_out.get("summary") or "")[:1200]
    sources = list(idx_out.get("sources") or [])[:12]
    facade = _slim_facade_context(topic)
    online_hints = _online_hints_for_topic(topic)
    pubmed_hints: list[dict[str, str]] = []
    try:
        from app.services.pubmed_lite import fetch_pubmed_article_hints

        pubmed_hints = fetch_pubmed_article_hints(topic, max_items=3, timeout=8.0)
    except Exception as e:
        logger.debug("pubmed_hints_skipped", extra={"error": str(e)[:120]})

    verification = _verify_enrichment_rules(summary, facade, idx_out)
    result_id = str(uuid.uuid4())
    row: dict[str, Any] = {
        "id": result_id,
        "job_id": job_id,
        "completed_at": round(time.time(), 2),
        "user_hash": job.get("user_hash"),
        "subject_id": job.get("subject_id"),
        "topic_fingerprint": str(job.get("topic_fingerprint") or "")[:80],
        "topic_preview": topic[:300],
        "indexed_summary_excerpt": summary,
        "facade_context": facade,
        "online_hints": online_hints[:8],
        "pubmed_hints": pubmed_hints[:5],
        "verification": verification,
        "sources_sample": [
            {"title": str(s.get("title") or s.get("name") or "")[:200], "url": str(s.get("url") or "")[:500]}
            if isinstance(s, dict)
            else {"title": str(s)[:200], "url": ""}
            for s in sources[:8]
        ],
        "llm_used_in_turn": bool(job.get("llm_used")),
        "response_source": job.get("response_source"),
        "promotion_status": "pending_review",
    }
    _append_enrichment_result(row)
    _maybe_notify_enrichment_ready(job, row)

    _mark_job(items, job_id, "indexed")
    data["items"] = items
    _write_json(_QUEUE_FILE, data)
    return {"ok": True, "job_id": job_id, "sources_n": len(sources)}


def _mark_job(items: list[dict], job_id: str, status: str) -> None:
    for i, it in enumerate(items):
        if str(it.get("id") or "") == job_id:
            items[i] = {**it, "status": status, "processed_at": round(time.time(), 2)}
            break
