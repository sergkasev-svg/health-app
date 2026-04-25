"""
Политика доступа: can_view_report, can_export_report, can_access_admin_quality, can_access_family_profile, can_access_clinic_account.
Изоляция по profile_id и clinic_id.
"""
from __future__ import annotations

from typing import Optional

from app.services.auth_models import AccessContext, UserRole


def can_view_report(ctx: AccessContext, report_owner_id: str, profile_id: Optional[str] = None) -> bool:
    """Пользователь может просматривать отчёт: владелец, семья (profile), admin, support."""
    if not report_owner_id:
        return False
    if ctx.user_id == report_owner_id:
        return True
    if ctx.profile_id and profile_id and ctx.profile_id == profile_id:
        return True
    if ctx.role in (UserRole.admin, UserRole.support_reviewer, UserRole.clinic_operator):
        return True
    return False


def can_export_report(ctx: AccessContext, report_owner_id: str, profile_id: Optional[str] = None) -> bool:
    """Право на экспорт отчёта: то же что view + premium/admin."""
    if not can_view_report(ctx, report_owner_id, profile_id):
        return False
    if ctx.role in (UserRole.admin, UserRole.clinic_operator, UserRole.premium_user):
        return True
    if ctx.role == UserRole.user:
        return True  # можно ограничить только premium при необходимости
    return ctx.role == UserRole.guest and ctx.user_id == report_owner_id


def can_access_admin_quality(ctx: AccessContext) -> bool:
    """Доступ к админке качества: только admin."""
    return ctx.role == UserRole.admin


def can_access_family_profile(ctx: AccessContext, profile_owner_id: str, profile_id: str) -> bool:
    """Доступ к семейному профилю: владелец или привязанный profile_id, или admin."""
    if ctx.user_id == profile_owner_id:
        return True
    if ctx.profile_id == profile_id:
        return True
    return ctx.role == UserRole.admin


def can_access_clinic_account(ctx: AccessContext, clinic_id: str) -> bool:
    """Доступ к данным клиники: clinic_operator этой клиники или admin."""
    if ctx.role == UserRole.admin:
        return True
    if ctx.role == UserRole.clinic_operator and ctx.clinic_id == clinic_id:
        return True
    return False
