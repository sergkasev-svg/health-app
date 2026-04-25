"""
Модели качества и админ-аналитики: события, провалы, воронка, дашборд.
Compact summaries, без сырых персональных данных.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ClinicalQualityEvent:
    event_id: str = ""
    timestamp: str = ""
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    state: Optional[str] = None
    urgency: Optional[str] = None
    red_flags: List[str] = field(default_factory=list)
    symptoms: List[str] = field(default_factory=list)
    hypotheses: List[str] = field(default_factory=list)
    user_hypotheses: List[str] = field(default_factory=list)
    recommended_labs: List[str] = field(default_factory=list)
    had_uploaded_files: bool = False
    file_types: List[str] = field(default_factory=list)
    physician_report_generated: bool = False
    care_plan_generated: bool = False
    followup_used: bool = False
    gated_features: List[str] = field(default_factory=list)
    debug_summary: Optional[Dict[str, Any]] = None
    quality_score: Optional[int] = None
    quality_grade: Optional[str] = None
    quality_tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "state": self.state,
            "urgency": self.urgency,
            "red_flags": self.red_flags,
            "symptoms": self.symptoms,
            "hypotheses": self.hypotheses,
            "user_hypotheses": self.user_hypotheses,
            "recommended_labs": self.recommended_labs,
            "had_uploaded_files": self.had_uploaded_files,
            "file_types": self.file_types,
            "physician_report_generated": self.physician_report_generated,
            "care_plan_generated": self.care_plan_generated,
            "followup_used": self.followup_used,
            "gated_features": self.gated_features,
            "debug_summary": self.debug_summary,
            "quality_score": self.quality_score,
            "quality_grade": self.quality_grade,
            "quality_tags": self.quality_tags,
        }


@dataclass
class FailureCase:
    case_id: str = ""
    timestamp: str = ""
    category: str = "other"  # hallucination / bad_triage / parsing_failure / weak_answer / duplicate_questions / gating_issue
    severity: str = "medium"  # low / medium / high / critical
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    short_description: str = ""
    raw_context_summary: Optional[Dict[str, Any]] = None
    resolution_status: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "timestamp": self.timestamp,
            "category": self.category,
            "severity": self.severity,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "short_description": self.short_description,
            "raw_context_summary": self.raw_context_summary,
            "resolution_status": self.resolution_status,
        }


@dataclass
class FunnelMetric:
    metric_id: str = ""
    timestamp: str = ""
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    stage: str = ""  # landing / onboarding_started / first_upload / first_value / upgrade_prompt / upgrade_click / activated / returned
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "stage": self.stage,
            "metadata": self.metadata,
        }


@dataclass
class AdminDashboardSnapshot:
    generated_at: str = ""
    total_sessions: int = 0
    total_reports: int = 0
    emergency_count: int = 0
    needs_more_data_count: int = 0
    request_labs_count: int = 0
    doctor_soon_count: int = 0
    self_care_count: int = 0
    physician_reports_count: int = 0
    followup_sessions_count: int = 0
    failure_cases_count: int = 0
    top_symptoms: List[Dict[str, Any]] = field(default_factory=list)
    top_lab_patterns: List[Dict[str, Any]] = field(default_factory=list)
    top_gated_features: List[Dict[str, Any]] = field(default_factory=list)
    funnel_summary: Dict[str, Any] = field(default_factory=dict)
    quality_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "totals": {
                "sessions": self.total_sessions,
                "reports": self.total_reports,
                "physician_reports": self.physician_reports_count,
                "followup_sessions": self.followup_sessions_count,
            },
            "states": {
                "emergency": self.emergency_count,
                "needs_more_data": self.needs_more_data_count,
                "request_labs": self.request_labs_count,
                "doctor_soon": self.doctor_soon_count,
                "self_care": self.self_care_count,
            },
            "quality": {
                "failure_cases": self.failure_cases_count,
                **self.quality_summary,
            },
            "top_symptoms": self.top_symptoms,
            "top_lab_patterns": self.top_lab_patterns,
            "top_gated_features": self.top_gated_features,
            "funnel_summary": self.funnel_summary,
        }


def compute_session_quality_score(
    event: Optional[ClinicalQualityEvent],
    failures: List[FailureCase],
) -> Dict[str, Any]:
    """
    Оценка 0–100 и grade A/B/C/D/F. Штрафы: hallucination -40, bad_triage -50, parsing -20, weak -15, duplicate -10, gating -50.
    """
    score = 100
    reasons: List[str] = []
    penalties = {
        "hallucination": 40,
        "bad_triage": 50,
        "parsing_failure": 20,
        "weak_answer": 15,
        "duplicate_questions": 10,
        "gating_issue": 50,
    }
    for f in failures or []:
        p = penalties.get(f.category, 10)
        score = max(0, score - p)
        reasons.append(f"{f.category}: {f.short_description[:80]}")
    if score >= 90:
        grade = "A"
    elif score >= 75:
        grade = "B"
    elif score >= 60:
        grade = "C"
    elif score >= 40:
        grade = "D"
    else:
        grade = "F"
    return {"score": score, "grade": grade, "reasons": reasons}
