"""
Модели аутентификации и ролей: AuthUser, UserRole, AccessContext, SessionTokenPayload.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class UserRole(str, Enum):
    guest = "guest"
    user = "user"
    premium_user = "premium_user"
    admin = "admin"
    clinic_operator = "clinic_operator"
    support_reviewer = "support_reviewer"


class AuthUser(BaseModel):
    """Минимальная модель пользователя для auth layer."""
    user_id: str = ""
    role: UserRole = UserRole.guest
    profile_id: Optional[str] = None
    clinic_id: Optional[str] = None
    email: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class SessionTokenPayload(BaseModel):
    """Полезная нагрузка JWT (access или refresh)."""
    sub: str = ""           # user_id
    role: str = "guest"
    profile_id: Optional[str] = None
    clinic_id: Optional[str] = None
    type: str = "access"    # access | refresh
    exp: Optional[int] = None
    iat: Optional[int] = None
    jti: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class AccessContext(BaseModel):
    """Контекст доступа текущего запроса (из JWT или fallback)."""
    user_id: str = ""
    role: UserRole = UserRole.guest
    profile_id: Optional[str] = None
    clinic_id: Optional[str] = None
    is_authenticated: bool = False
    is_admin: bool = False
    is_clinic_operator: bool = False
    token_payload: Optional[SessionTokenPayload] = None
    source: str = "guest"   # guest | jwt | admin_token

    @classmethod
    def guest(cls, user_id: str = "default") -> "AccessContext":
        return cls(
            user_id=user_id,
            role=UserRole.guest,
            is_authenticated=False,
            source="guest",
        )

    def has_role(self, role: UserRole) -> bool:
        return self.role == role

    def has_any_role(self, roles: List[UserRole]) -> bool:
        return self.role in roles
