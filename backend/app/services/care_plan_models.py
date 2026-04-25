"""
Модели плана действий (Care Plan): действия, мониторинг, чекпоинты.
Только безопасные рекомендации: наблюдение, анализы, визит к врачу.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CareAction:
    """Одно действие в плане."""
    title: str = ""
    description: str = ""
    priority: str = "soon"  # now / soon / routine
    timeframe: Optional[str] = None
    category: str = "monitoring"  # self_care / monitoring / labs / doctor_visit / emergency / lifestyle
    safe_only: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "timeframe": self.timeframe,
            "category": self.category,
            "safe_only": self.safe_only,
        }


@dataclass
class MonitoringTarget:
    """Что отслеживать и зачем."""
    name: str = ""
    why_it_matters: str = ""
    frequency: Optional[str] = None
    escalation_if: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "why_it_matters": self.why_it_matters,
            "frequency": self.frequency,
            "escalation_if": self.escalation_if,
        }


@dataclass
class FollowUpCheckpoint:
    """Условие смены маршрута."""
    trigger: str = ""
    recommended_step: str = ""
    urgency: str = "routine"  # routine / sooner / urgent / emergency

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger": self.trigger,
            "recommended_step": self.recommended_step,
            "urgency": self.urgency,
        }


@dataclass
class CarePlan:
    """Полный план действий по состоянию."""
    state: str = "needs_more_data"
    summary: str = ""
    actions: List[CareAction] = field(default_factory=list)
    monitoring: List[MonitoringTarget] = field(default_factory=list)
    checkpoints: List[FollowUpCheckpoint] = field(default_factory=list)
    duration_hint: Optional[str] = None
    next_review: Optional[str] = None
    doctor_followup_needed: bool = False
    emergency_override: bool = False
    debug: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "summary": self.summary,
            "actions": [a.to_dict() for a in self.actions],
            "monitoring": [m.to_dict() for m in self.monitoring],
            "checkpoints": [c.to_dict() for c in self.checkpoints],
            "duration_hint": self.duration_hint,
            "next_review": self.next_review,
            "doctor_followup_needed": self.doctor_followup_needed,
            "emergency_override": self.emergency_override,
            "debug": self.debug,
        }
