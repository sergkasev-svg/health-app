"""Сохранение отчётов в БД."""
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models import Report, User


def save_report(
    db: Session,
    user_id: int,
    data: Dict[str, Any],
    result: Dict[str, Any],
) -> Report:
    """Сохранить отчёт в БД."""
    report = Report(user_id=user_id, data=data, result=result)
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def get_user_reports(
    db: Session,
    user_id: int,
    limit: int = 50,
) -> list[Report]:
    """Получить отчёты пользователя (последние)."""
    return (
        db.query(Report)
        .filter(Report.user_id == user_id)
        .order_by(Report.created_at.desc())
        .limit(limit)
        .all()
    )


def get_report_by_id(
    db: Session,
    report_id: int,
    user_id: Optional[int] = None,
) -> Optional[Report]:
    """Получить отчёт по ID (с проверкой user_id если задан)."""
    query = db.query(Report).filter(Report.id == report_id)
    if user_id is not None:
        query = query.filter(Report.user_id == user_id)
    return query.first()
