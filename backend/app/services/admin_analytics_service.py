"""
Admin Analytics: дашборд, топ симптомов, лаб-паттернов, воронка, качество, распределение state.
Читает из QualityStore. Без персональных данных в агрегатах.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.services.quality_models import AdminDashboardSnapshot
from app.services.quality_store import QualityStore


def _parse_ts(ts: str) -> Optional[datetime]:
    try:
        if "Z" in ts:
            ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _days_ago_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")


class AdminAnalyticsService:
    def __init__(self, store: Optional[QualityStore] = None):
        self._store = store or QualityStore()

    def _events_since(self, days: int) -> List[Dict[str, Any]]:
        events = self._store.get_events(limit=5000)
        cutoff = _days_ago_iso(days)
        return [e for e in events if (e.get("timestamp") or "") >= cutoff]

    def _failures_since(self, days: int) -> List[Dict[str, Any]]:
        failures = self._store.get_failures(limit=2000)
        cutoff = _days_ago_iso(days)
        return [f for f in failures if (f.get("timestamp") or "") >= cutoff]

    def _funnel_since(self, days: int) -> List[Dict[str, Any]]:
        metrics = self._store.get_funnel_metrics(limit=5000)
        cutoff = _days_ago_iso(days)
        return [m for m in metrics if (m.get("timestamp") or "") >= cutoff]

    def get_state_distribution(self, days: int = 7) -> Dict[str, int]:
        events = self._events_since(days)
        c: Counter = Counter()
        for e in events:
            s = e.get("state") or "unknown"
            c[s] += 1
        return dict(c)

    def get_failure_breakdown(self, days: int = 7) -> Dict[str, Any]:
        failures = self._failures_since(days)
        by_cat: Counter = Counter()
        by_sev: Counter = Counter()
        for f in failures:
            by_cat[f.get("category") or "other"] += 1
            by_sev[f.get("severity") or "medium"] += 1
        return {
            "total": len(failures),
            "by_category": dict(by_cat),
            "by_severity": dict(by_sev),
        }

    def get_top_symptoms(self, days: int = 7, limit: int = 10) -> List[Dict[str, Any]]:
        events = self._events_since(days)
        c: Counter = Counter()
        for e in events:
            for s in e.get("symptoms") or []:
                if s:
                    c[str(s).strip()] += 1
        return [{"symptom": k, "count": v} for k, v in c.most_common(limit)]

    def get_top_lab_patterns(self, days: int = 7, limit: int = 10) -> List[Dict[str, Any]]:
        events = self._events_since(days)
        c: Counter = Counter()
        for e in events:
            for lab in e.get("recommended_labs") or []:
                if lab:
                    c[str(lab).strip()] += 1
        return [{"lab": k, "count": v} for k, v in c.most_common(limit)]

    def get_top_gated_features(self, days: int = 7, limit: int = 10) -> List[Dict[str, Any]]:
        events = self._events_since(days)
        c: Counter = Counter()
        for e in events:
            for g in e.get("gated_features") or []:
                if g:
                    c[str(g)] += 1
        return [{"feature": k, "count": v} for k, v in c.most_common(limit)]

    def get_funnel_summary(self, days: int = 7) -> Dict[str, Any]:
        metrics = self._funnel_since(days)
        c: Counter = Counter()
        for m in metrics:
            stage = m.get("stage") or "unknown"
            c[stage] += 1
        return {"stages": dict(c), "total_events": len(metrics)}

    def get_quality_summary(self, days: int = 7) -> Dict[str, Any]:
        failures = self._failures_since(days)
        breakdown = self.get_failure_breakdown(days)
        return {
            "failure_cases": len(failures),
            "hallucinations": breakdown.get("by_category", {}).get("hallucination", 0),
            "bad_triage": breakdown.get("by_category", {}).get("bad_triage", 0),
            "parsing_failures": breakdown.get("by_category", {}).get("parsing_failure", 0),
            "weak_answer": breakdown.get("by_category", {}).get("weak_answer", 0),
            "duplicate_questions": breakdown.get("by_category", {}).get("duplicate_questions", 0),
            "gating_issue": breakdown.get("by_category", {}).get("gating_issue", 0),
        }

    def build_dashboard_snapshot(self, days: int = 7) -> AdminDashboardSnapshot:
        events = self._events_since(days)
        failures = self._failures_since(days)
        states = self.get_state_distribution(days)
        quality = self.get_quality_summary(days)
        funnel = self.get_funnel_summary(days)
        top_s = self.get_top_symptoms(days, 10)
        top_l = self.get_top_lab_patterns(days, 10)
        top_g = self.get_top_gated_features(days, 5)
        return AdminDashboardSnapshot(
            generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            total_sessions=len(events),
            total_reports=len([e for e in events if e.get("care_plan_generated") or e.get("physician_report_generated")]),
            emergency_count=states.get("emergency", 0),
            needs_more_data_count=states.get("needs_more_data", 0),
            request_labs_count=states.get("request_labs", 0),
            doctor_soon_count=states.get("doctor_soon", 0),
            self_care_count=states.get("self_care", 0),
            physician_reports_count=len([e for e in events if e.get("physician_report_generated")]),
            followup_sessions_count=len([e for e in events if e.get("followup_used")]),
            failure_cases_count=len(failures),
            top_symptoms=top_s,
            top_lab_patterns=top_l,
            top_gated_features=top_g,
            funnel_summary=funnel,
            quality_summary=quality,
        )
