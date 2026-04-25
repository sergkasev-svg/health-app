"""
Admin Quality API: дашборд, события, провалы, воронка, топ симптомов/лабов.
Защита: get_admin_context (JWT admin или X-Admin-Token / ADMIN_TOKEN / ADMIN_QUALITY_TOKEN).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps_auth import get_admin_context
from app.services.admin_analytics_service import AdminAnalyticsService
from app.services.audit_logger import log_audit_event
from app.services.auth_models import AccessContext
from app.services.quality_store import QualityStore
from app.services.weekly_quality_report import WeeklyQualityReportService


router = APIRouter(prefix="/api/admin/quality", tags=["admin-quality"], dependencies=[])


@router.get("/dashboard")
def get_dashboard(
    days: int = Query(7, ge=1, le=90),
    ctx: AccessContext = Depends(get_admin_context),
):
    """Снимок дашборда за последние days дней."""
    log_audit_event("admin_quality_dashboard", target_type="dashboard", actor_user_id=ctx.user_id, actor_role=ctx.role.value)
    svc = AdminAnalyticsService()
    snapshot = svc.build_dashboard_snapshot(days)
    return snapshot.to_dict()


@router.get("/events")
def get_events(
    limit: int = Query(100, ge=1, le=500),
    ctx: AccessContext = Depends(get_admin_context),
):
    log_audit_event("admin_quality_events", target_type="events", actor_user_id=ctx.user_id, actor_role=ctx.role.value)
    store = QualityStore()
    return {"events": store.get_events(limit=limit)}


@router.get("/failures")
def get_failures(
    limit: int = Query(100, ge=1, le=500),
    ctx: AccessContext = Depends(get_admin_context),
):
    log_audit_event("admin_quality_failures", target_type="failures", actor_user_id=ctx.user_id, actor_role=ctx.role.value)
    store = QualityStore()
    return {"failures": store.get_failures(limit=limit)}


@router.get("/funnel")
def get_funnel(
    days: int = Query(7, ge=1, le=90),
    ctx: AccessContext = Depends(get_admin_context),
):
    svc = AdminAnalyticsService()
    return svc.get_funnel_summary(days)


@router.get("/states")
def get_states(
    days: int = Query(7, ge=1, le=90),
    ctx: AccessContext = Depends(get_admin_context),
):
    svc = AdminAnalyticsService()
    return svc.get_state_distribution(days)


@router.get("/top-symptoms")
def get_top_symptoms(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(10, ge=1, le=50),
    ctx: AccessContext = Depends(get_admin_context),
):
    svc = AdminAnalyticsService()
    return {"top_symptoms": svc.get_top_symptoms(days, limit)}


@router.get("/top-lab-patterns")
def get_top_lab_patterns(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(10, ge=1, le=50),
    ctx: AccessContext = Depends(get_admin_context),
):
    svc = AdminAnalyticsService()
    return {"top_lab_patterns": svc.get_top_lab_patterns(days, limit)}


@router.get("/weekly-report")
def get_weekly_report(
    days: int = Query(7, ge=1, le=90),
    ctx: AccessContext = Depends(get_admin_context),
):
    log_audit_event("admin_quality_weekly_report", target_type="weekly_report", actor_user_id=ctx.user_id, actor_role=ctx.role.value)
    svc = WeeklyQualityReportService()
    return svc.build_report(days)
