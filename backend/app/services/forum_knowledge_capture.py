"""
Явная выгрузка ценных фрагментов форума в очередь knowledge flywheel.

Поток: тематический модератор/админ отмечает материал → глобальное ревью
(`/review/learning-candidates`) → при одобрении — экспорт в offline-справочник
(`scripts.export_reviewed_cases_to_knowledge`).

Без автозахвата всего форума: только ручной POST, дедуп по comment_id и по
одному «открывающему» снимку на тему (пока кейс не отклонён в flywheel).
"""
from __future__ import annotations

from typing import Any, Optional

from app.services import forum_store as forum
from app.services.knowledge_flywheel import capture_learning_candidate, list_learning_candidates

_MIN_CAPTURE_CHARS = 80
_MAX_NOTE = 2000


def _forum_capture_is_duplicate(
    *,
    comment_id: Optional[str],
    thread_id: str,
    capture_kind: str,
) -> bool:
    cid = str(comment_id or "").strip()
    tid = str(thread_id or "").strip()
    kind = str(capture_kind or "").strip()
    for item in list_learning_candidates(limit=2500):
        st = str(item.get("review_status") or "pending").strip().lower()
        if st == "rejected":
            continue
        prov = item.get("provenance")
        if not isinstance(prov, dict):
            continue
        if str(prov.get("source") or "") != "forum":
            continue
        if cid and str(prov.get("comment_id") or "") == cid:
            return True
        if (not cid) and kind == "thread_opener":
            if str(prov.get("thread_id") or "") == tid and str(prov.get("capture_kind") or "") == "thread_opener":
                return True
    return False


def propose_forum_content_for_knowledge(
    *,
    thread_id: str,
    comment_id: Optional[str] = None,
    proposed_by_user_id: str = "",
    moderator_note: str = "",
) -> dict[str, Any]:
    """
    Собирает анонимизируемый снимок темы (и опционально одного комментария) в flywheel.

    Возвращает {ok, candidate_id?, provenance?, reason?, min_chars?}.
    """
    tid = str(thread_id or "").strip()
    if not tid:
        return {"ok": False, "reason": "missing_thread_id"}

    thread = forum.get_thread(tid)
    if not thread:
        return {"ok": False, "reason": "thread_not_found"}

    branch_id = str(thread.get("branch_id") or "").strip()
    t_status = str(thread.get("status") or "").strip().lower()
    if t_status != "approved":
        return {"ok": False, "reason": "thread_not_approved"}

    title = str(thread.get("title") or "").strip()
    t_body = str(thread.get("content") or "").strip()

    narrative = ""
    capture_kind = "thread_opener"
    cid = str(comment_id or "").strip()

    if cid:
        comment = forum.get_comment(cid)
        if not comment:
            return {"ok": False, "reason": "comment_not_found"}
        if str(comment.get("thread_id") or "") != tid:
            return {"ok": False, "reason": "comment_thread_mismatch"}
        if str(comment.get("branch_id") or "") != branch_id:
            return {"ok": False, "reason": "comment_branch_mismatch"}
        c_status = str(comment.get("status") or "").strip().lower()
        if c_status != "approved":
            return {"ok": False, "reason": "comment_not_approved"}
        c_body = str(comment.get("content") or "").strip()
        capture_kind = "expert_comment"
        narrative = (
            f"Тема (заголовок): {title}\n\n"
            f"Контекст темы:\n{t_body[:2200]}\n\n"
            f"Выбранный комментарий:\n{c_body[:2200]}"
        )
    else:
        narrative = f"{title}\n\n{t_body}".strip()

    if len(narrative) < _MIN_CAPTURE_CHARS:
        return {"ok": False, "reason": "content_too_short", "min_chars": _MIN_CAPTURE_CHARS}

    if _forum_capture_is_duplicate(comment_id=cid or None, thread_id=tid, capture_kind=capture_kind):
        return {"ok": False, "reason": "already_queued_or_promoted"}

    note = str(moderator_note or "").strip()[:_MAX_NOTE]
    prov: dict[str, str] = {
        "source": "forum",
        "branch_id": branch_id,
        "thread_id": tid,
        "capture_kind": capture_kind,
    }
    if cid:
        prov["comment_id"] = cid

    item = capture_learning_candidate(
        user_id=str(proposed_by_user_id or "forum_mod")[:80],
        question=(title[:1500] if title else narrative[:200]),
        response=narrative[:4000],
        structured={
            "chief_complaint": (title[:500] if title else narrative[:300]),
            "severity": "YELLOW",
            "top_hypotheses": [],
            "recommended_labs": [],
        },
        orchestrator_state={
            "protocol_source": "forum_vetted",
            "complaint": (title[:300] if title else narrative[:300]),
        },
        report={"user_summary": note},
        response_source="forum_moderator_capture",
        llm_used=False,
        provenance=prov,
    )
    return {"ok": True, "candidate_id": item.get("id"), "provenance": prov}
