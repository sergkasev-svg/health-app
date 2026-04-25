"""
Сервис аутентификации: создание/верификация токенов, контекст доступа, проверка ролей.
Guest fallback; admin только при явной настройке или JWT с ролью admin.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Optional

import jwt
from jwt import PyJWKClientError, PyJWTError

from app.core.settings import get_settings
from app.services.auth_models import AccessContext, AuthUser, SessionTokenPayload, UserRole
from app.services.auth_store import get_user_by_session

logger = logging.getLogger(__name__)


def create_access_token(
    user_id: str,
    role: str = "user",
    profile_id: Optional[str] = None,
    clinic_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> str:
    settings = get_settings()
    now = int(time.time())
    exp = now + settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    payload = {
        "sub": user_id,
        "role": role,
        "profile_id": profile_id,
        "clinic_id": clinic_id,
        "type": "access",
        "exp": exp,
        "iat": now,
        "jti": str(uuid.uuid4()),
        **(extra or {}),
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm="HS256",
    )


def create_refresh_token(
    user_id: str,
    role: str = "user",
    extra: Optional[dict] = None,
) -> str:
    settings = get_settings()
    now = int(time.time())
    exp = now + settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60
    payload = {
        "sub": user_id,
        "role": role,
        "type": "refresh",
        "exp": exp,
        "iat": now,
        "jti": str(uuid.uuid4()),
        **(extra or {}),
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm="HS256",
    )


def verify_token(token: str) -> Optional[SessionTokenPayload]:
    if not token or not token.strip():
        return None
    settings = get_settings()
    try:
        payload = jwt.decode(
            token.strip(),
            settings.JWT_SECRET,
            algorithms=["HS256"],
        )
        return SessionTokenPayload(
            sub=payload.get("sub", ""),
            role=payload.get("role", "guest"),
            profile_id=payload.get("profile_id"),
            clinic_id=payload.get("clinic_id"),
            type=payload.get("type", "access"),
            exp=payload.get("exp"),
            iat=payload.get("iat"),
            jti=payload.get("jti"),
            extra={k: v for k, v in payload.items() if k not in ("sub", "role", "profile_id", "clinic_id", "type", "exp", "iat", "jti")},
        )
    except (PyJWTError, PyJWKClientError) as e:
        logger.debug("token_verify_failed", extra={"error": str(e)})
        return None


def _role_from_string(s: str) -> UserRole:
    try:
        return UserRole(s)
    except ValueError:
        return UserRole.guest


def get_current_access_context(
    bearer_token: Optional[str] = None,
    x_user_id: Optional[str] = None,
    admin_token_header: Optional[str] = None,
) -> AccessContext:
    """
    Собирает контекст доступа: JWT > файловая сессия (Bearer из login) > admin_token > guest.
    """
    settings = get_settings()

    # 1) Bearer JWT
    if bearer_token:
        if bearer_token.lower().startswith("bearer "):
            token = bearer_token[7:].strip()
        else:
            token = bearer_token.strip()
        payload = verify_token(token)
        if payload:
            role = _role_from_string(payload.role)
            return AccessContext(
                user_id=payload.sub or "default",
                role=role,
                profile_id=payload.profile_id,
                clinic_id=payload.clinic_id,
                is_authenticated=True,
                is_admin=role == UserRole.admin,
                is_clinic_operator=role == UserRole.clinic_operator,
                token_payload=payload,
                source="jwt",
            )

    # 1b) Файловая сессия (Bearer = token из /api/user/login — не JWT)
    if bearer_token:
        if bearer_token.lower().startswith("bearer "):
            raw_tok = bearer_token[7:].strip()
        else:
            raw_tok = bearer_token.strip()
        sess_user = get_user_by_session(raw_tok)
        if sess_user:
            uid = (sess_user.get("user_id") or "").strip()
            if uid:
                role = _role_from_string(sess_user.get("role") or "user")
                return AccessContext(
                    user_id=uid,
                    role=role,
                    is_authenticated=True,
                    is_admin=role == UserRole.admin,
                    is_clinic_operator=role == UserRole.clinic_operator,
                    source="session",
                )

    # 2) Admin fallback token (ADMIN_TOKEN или legacy ADMIN_QUALITY_TOKEN)
    admin_token = settings.ADMIN_TOKEN or os.environ.get("ADMIN_QUALITY_TOKEN", "").strip()
    if admin_token and admin_token_header and admin_token_header.strip() == admin_token:
        user_id = x_user_id.strip() if x_user_id else "admin-fallback"
        return AccessContext(
            user_id=user_id,
            role=UserRole.admin,
            is_authenticated=True,
            is_admin=True,
            is_clinic_operator=False,
            source="admin_token",
        )

    # 3) Guest: по X-User-Id или default
    user_id = (x_user_id or "").strip() or "default"
    return AccessContext.guest(user_id=user_id)


def has_role(ctx: AccessContext, role: UserRole) -> bool:
    return ctx.role == role


def has_any_role(ctx: AccessContext, roles: list) -> bool:
    return ctx.role in roles
