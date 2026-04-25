"""
FastAPI dependencies для аутентификации и ролей.
get_optional_access_context, get_required_user_context, get_admin_context, get_clinic_operator_context.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException, Request

from app.services.auth_models import AccessContext, UserRole
from app.services.auth_service import get_current_access_context


async def get_optional_access_context(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
) -> AccessContext:
    """Контекст доступа: может быть guest. Для маршрутов, где авторизация опциональна."""
    return get_current_access_context(
        bearer_token=authorization,
        x_user_id=x_user_id,
        admin_token_header=x_admin_token,
    )


async def get_required_user_context(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
) -> AccessContext:
    """Требуется хотя бы идентифицированный пользователь (user_id). Guest с default допускается."""
    ctx = get_current_access_context(
        bearer_token=authorization,
        x_user_id=x_user_id,
        admin_token_header=x_admin_token,
    )
    if not ctx.user_id:
        raise HTTPException(status_code=401, detail="User context required")
    return ctx


async def get_admin_context(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
) -> AccessContext:
    """Только admin (JWT с ролью admin или валидный ADMIN_TOKEN)."""
    ctx = get_current_access_context(
        bearer_token=authorization,
        x_user_id=x_user_id,
        admin_token_header=x_admin_token,
    )
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return ctx


async def get_clinic_operator_context(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
) -> AccessContext:
    """Clinic operator или admin."""
    ctx = get_current_access_context(
        bearer_token=authorization,
        x_user_id=x_user_id,
        admin_token_header=x_admin_token,
    )
    if ctx.role not in (UserRole.clinic_operator, UserRole.admin):
        raise HTTPException(status_code=403, detail="Clinic operator or admin access required")
    return ctx
