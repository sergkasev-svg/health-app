"""
Memory: сохранение анализа в историю, маркеры, напоминания о повторных проверках.
Используется для «Михаил помнит прошлые анализы» и динамики по маркерам.
"""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models import FollowUpReminder, MarkerSnapshot, ReportHistory


def _safe_str(v: Any) -> str:
    return "" if v is None else str(v)


def store_report(
    db: Session,
    user_id: int,
    report_type: str,
    payload: dict,
    result: dict,
    source_name: str | None = None,
) -> ReportHistory:
    report = ReportHistory(
        user_id=user_id,
        report_type=report_type or "unknown",
        source_name=source_name,
        raw_payload=payload,
        ai_result=result,
        summary_text=(result.get("text") or result.get("summary") or "")[:4000],
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def store_markers(
    db: Session,
    user_id: int,
    report_id: int,
    lab_markers: Dict[str, Any],
) -> None:
    for key, value in (lab_markers or {}).items():
        status = "unknown"
        numeric = None
        unit = None
        if isinstance(value, dict):
            raw_value = value.get("value")
            status = value.get("status", "unknown")
            numeric = _safe_str(value.get("numeric") or value.get("value"))
            unit = value.get("unit")
        else:
            raw_value = value
            if isinstance(value, (int, float)):
                numeric = str(value)
        row = MarkerSnapshot(
            report_id=report_id,
            user_id=user_id,
            marker_key=key,
            marker_value=_safe_str(raw_value),
            marker_numeric=numeric,
            marker_unit=unit,
            marker_status=status,
        )
        db.add(row)
    db.commit()


def create_followup_reminders(
    db: Session,
    user_id: int,
    report_id: int,
    result: dict,
) -> List[FollowUpReminder]:
    reminders = []
    text = (result.get("text") or result.get("summary") or "").lower()
    candidates = []
    if "повтор оак" in text or "repeat cbc" in text or "оак в динамике" in text:
        candidates.append(("repeat_cbc", "Повторить общий анализ крови"))
    if "crp" in text:
        candidates.append(("check_crp", "Проверить CRP"))
    if "липид" in text or "apob" in text or "лпнп" in text:
        candidates.append(("repeat_lipid", "Контроль липидного профиля"))
    for reminder_type, notes in candidates:
        r = FollowUpReminder(
            user_id=user_id,
            report_id=report_id,
            reminder_type=reminder_type,
            notes=notes,
        )
        db.add(r)
        reminders.append(r)
    db.commit()
    return reminders


def save_analysis_with_memory(
    db: Session,
    user_id: int,
    payload: dict,
    result: dict,
    source_name: str | None = None,
) -> dict:
    report_type = result.get("report_type") or payload.get("report_type") or "unknown"
    report = store_report(db, user_id, report_type, payload, result, source_name)
    lab_markers = payload.get("lab_markers") or {}
    store_markers(db, user_id, report.id, lab_markers)
    reminders = create_followup_reminders(db, user_id, report.id, result)
    result["memory"] = {
        "report_id": report.id,
        "saved": True,
        "reminders_created": len(reminders),
    }
    return result


def get_recent_reports(
    db: Session,
    user_id: int,
    limit: int = 10,
):
    return (
        db.query(ReportHistory)
        .filter(ReportHistory.user_id == user_id)
        .order_by(ReportHistory.created_at.desc())
        .limit(limit)
        .all()
    )


def get_marker_history(
    db: Session,
    user_id: int,
    marker_key: str,
    limit: int = 20,
):
    return (
        db.query(MarkerSnapshot)
        .filter(
            MarkerSnapshot.user_id == user_id,
            MarkerSnapshot.marker_key == marker_key,
        )
        .order_by(MarkerSnapshot.created_at.desc())
        .limit(limit)
        .all()
    )


def get_reminders(
    db: Session,
    user_id: int,
    limit: int = 20,
    include_done: bool = False,
):
    """Напоминания о повторных проверках (ОАК, CRP, липиды и т.д.) для дашборда."""
    q = db.query(FollowUpReminder).filter(FollowUpReminder.user_id == user_id)
    if not include_done:
        q = q.filter(FollowUpReminder.is_done.is_(False))
    return q.order_by(FollowUpReminder.created_at.desc()).limit(limit).all()
