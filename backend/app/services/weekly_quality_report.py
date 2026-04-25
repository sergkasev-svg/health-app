"""
Еженедельный отчёт по качеству: сессии, state, провалы, рекомендации.
"""
from __future__ import annotations

from typing import Any, Dict

from app.services.admin_analytics_service import AdminAnalyticsService
from app.services.quality_feedback_loop import collect_recent_failures, suggest_rule_improvements, suggest_prompt_improvements
from app.services.quality_store import QualityStore


class WeeklyQualityReportService:
    def __init__(self, store: QualityStore | None = None, analytics: AdminAnalyticsService | None = None):
        self._store = store or QualityStore()
        self._analytics = analytics or AdminAnalyticsService(store=self._store)

    def build_report(self, days: int = 7) -> Dict[str, Any]:
        snapshot = self._analytics.build_dashboard_snapshot(days)
        failures = collect_recent_failures(self._store, limit=500)
        rule_suggestions = suggest_rule_improvements(failures)
        prompt_suggestions = suggest_prompt_improvements(failures)
        return {
            "period_days": days,
            "generated_at": snapshot.generated_at,
            "sessions": snapshot.total_sessions,
            "reports": snapshot.total_reports,
            "state_distribution": snapshot.to_dict().get("states", {}),
            "failure_breakdown": snapshot.quality_summary,
            "worst_recurring": rule_suggestions[:5],
            "recommendations": {
                "rules": rule_suggestions,
                "prompts": prompt_suggestions,
            },
            "funnel_summary": snapshot.funnel_summary,
            "top_symptoms": snapshot.top_symptoms[:5],
            "top_lab_patterns": snapshot.top_lab_patterns[:5],
        }
