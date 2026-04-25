"""
API истории анализов, маркеров и динамики (Memory + Dynamics).
Для подписки: «Михаил помнит прошлые анализы», тренды по LDL, Hb, СОЭ, ALT, ферритину и т.д.
"""
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps_auth import get_optional_access_context
from app.database import get_db
from app.models import User
from app.services.auth_models import AccessContext
from app.services.dynamics_service import (
    RECOMMENDED_MARKERS_FOR_TRENDS,
    build_dynamics_summary,
)
from app.services.memory_service import get_marker_history, get_recent_reports, get_reminders

router = APIRouter(prefix="/api", tags=["memory"])


def _get_or_create_db_user(db: Session, ctx: AccessContext) -> Optional[User]:
    """Получить или создать User в БД из AccessContext (для memory нужен integer id в связанных таблицах)."""
    uid = (ctx.user_id or "").strip()
    if not uid or uid == "default":
        return None
    # Legacy: JWT / тесты с числовым sub
    if uid.isdigit():
        user_id_int = int(uid)
        user = db.query(User).filter(User.id == user_id_int).first()
        if not user:
            try:
                user = User(id=user_id_int)
                db.add(user)
                db.commit()
                db.refresh(user)
            except Exception:
                db.rollback()
                return None
        return user
    # Сессионный логин: u_..., pk_... — маппинг через auth_subject
    user = db.query(User).filter(User.auth_subject == uid).first()
    if user:
        return user
    try:
        user = User(auth_subject=uid)
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        return None
    return user


def _require_db_user(
    ctx: AccessContext = Depends(get_optional_access_context),
    db: Session = Depends(get_db),
) -> User:
    """Для memory-эндпоинтов нужен пользователь в БД (integer id)."""
    user = _get_or_create_db_user(db, ctx)
    if not user:
        raise HTTPException(
            status_code=403,
            detail="Для доступа к истории и динамике нужна авторизация.",
        )
    return user


@router.get("/memory/reports")
def recent_reports(
    limit: int = 10,
    db: Session = Depends(get_db),
    user: User = Depends(_require_db_user),
):
    """Последние сохранённые отчёты пользователя."""
    rows = get_recent_reports(db, user.id, limit)
    return {
        "items": [
            {
                "id": r.id,
                "report_type": r.report_type,
                "summary_text": (r.summary_text or "")[:500],
                "created_at": str(r.created_at),
            }
            for r in rows
        ]
    }


@router.get("/memory/reminders")
def list_reminders(
    limit: int = 20,
    include_done: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(_require_db_user),
):
    """Напоминания о повторных проверках (повтор ОАК, CRP, липиды и т.д.)."""
    rows = get_reminders(db, user.id, limit=limit, include_done=include_done)
    return {
        "items": [
            {
                "id": r.id,
                "reminder_type": r.reminder_type,
                "notes": r.notes or "",
                "due_date": str(r.due_date) if r.due_date else None,
                "is_done": r.is_done,
                "created_at": str(r.created_at),
            }
            for r in rows
        ]
    }


@router.get("/memory/marker/{marker_key}")
def marker_history(
    marker_key: str,
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(_require_db_user),
):
    """История значений маркера (для графиков и динамики)."""
    rows = get_marker_history(db, user.id, marker_key, limit)
    return {
        "marker_key": marker_key,
        "items": [
            {
                "value": r.marker_value,
                "numeric": r.marker_numeric,
                "status": r.marker_status,
                "created_at": str(r.created_at),
            }
            for r in rows
        ],
    }


class DynamicsPayload(BaseModel):
    marker_keys: Optional[List[str]] = None


@router.post("/memory/dynamics")
def marker_dynamics(
    payload: DynamicsPayload,
    db: Session = Depends(get_db),
    user: User = Depends(_require_db_user),
):
    """Сравнение последних двух значений по каждому маркеру (тренд вверх/вниз/стабильно)."""
    marker_keys = payload.marker_keys or RECOMMENDED_MARKERS_FOR_TRENDS
    return build_dynamics_summary(db, user.id, marker_keys)
