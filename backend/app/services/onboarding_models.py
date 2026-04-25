"""
Модели онбординга и конверсии: шаги, состояние, сигналы, решение об апгрейде.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class OnboardingStep:
    step_id: str = ""
    title: str = ""
    description: str = ""
    cta: Optional[str] = None
    step_type: str = "intro"  # intro / profile / symptom_entry / lab_upload / first_result / upgrade / followup
    required: bool = False
    completed: bool = False
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "description": self.description,
            "cta": self.cta,
            "step_type": self.step_type,
            "required": self.required,
            "completed": self.completed,
            "metadata": self.metadata or {},
        }


@dataclass
class OnboardingState:
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    is_new_user: bool = True
    current_step_id: Optional[str] = None
    completed_steps: List[str] = field(default_factory=list)
    skipped_steps: List[str] = field(default_factory=list)
    first_value_reached: bool = False
    first_upload_done: bool = False
    first_report_done: bool = False
    first_followup_prompt_shown: bool = False
    first_upgrade_prompt_shown: bool = False
    onboarding_version: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "is_new_user": self.is_new_user,
            "current_step_id": self.current_step_id,
            "completed_steps": self.completed_steps,
            "skipped_steps": self.skipped_steps,
            "first_value_reached": self.first_value_reached,
            "first_upload_done": self.first_upload_done,
            "first_report_done": self.first_report_done,
            "first_followup_prompt_shown": self.first_followup_prompt_shown,
            "first_upgrade_prompt_shown": self.first_upgrade_prompt_shown,
            "onboarding_version": self.onboarding_version,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> OnboardingState:
        d = d or {}
        return cls(
            user_id=d.get("user_id"),
            session_id=d.get("session_id"),
            is_new_user=bool(d.get("is_new_user", True)),
            current_step_id=d.get("current_step_id"),
            completed_steps=list(d.get("completed_steps") or []),
            skipped_steps=list(d.get("skipped_steps") or []),
            first_value_reached=bool(d.get("first_value_reached")),
            first_upload_done=bool(d.get("first_upload_done")),
            first_report_done=bool(d.get("first_report_done")),
            first_followup_prompt_shown=bool(d.get("first_followup_prompt_shown")),
            first_upgrade_prompt_shown=bool(d.get("first_upgrade_prompt_shown")),
            onboarding_version=d.get("onboarding_version"),
            updated_at=d.get("updated_at"),
        )


@dataclass
class ConversionSignal:
    signal_id: str = ""
    signal_type: str = ""  # lab_uploaded / report_viewed / physician_report_teased / followup_return / repeat_usage / trend_value
    weight: float = 1.0
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ConversionDecision:
    should_show_upgrade: bool = False
    timing: Optional[str] = None
    placement: Optional[str] = None  # after_first_result / after_report / after_locked_feature / followup_return / dashboard_banner / report_footer
    offer_id: Optional[str] = None
    reason: Optional[str] = None
    message: Optional[str] = None
    offer: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "should_show_upgrade": self.should_show_upgrade,
            "timing": self.timing,
            "placement": self.placement,
            "offer_id": self.offer_id,
            "reason": self.reason,
            "message": self.message,
            "offer": self.offer,
        }
