"""
Memory models для Михаила: симптомы, анализы, заданные вопросы, follow-up план.
Только клинически релевантные данные, компактные суммари.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SymptomRecord:
    """Запись о симптоме из диалога."""
    name: str = ""
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    status: Optional[str] = None
    severity: Optional[str] = None
    source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "status": self.status,
            "severity": self.severity,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SymptomRecord":
        d = d or {}
        return cls(
            name=str(d.get("name") or ""),
            first_seen_at=d.get("first_seen_at"),
            last_seen_at=d.get("last_seen_at"),
            status=d.get("status"),
            severity=d.get("severity"),
            source=d.get("source"),
        )


@dataclass
class LabRecord:
    """Одна запись лабораторного показателя (одна дата/файл)."""
    marker_name: str = ""
    value: Optional[float] = None
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    flag: Optional[str] = None
    date: Optional[str] = None
    source_file: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "marker_name": self.marker_name,
            "value": self.value,
            "unit": self.unit,
            "ref_low": self.ref_low,
            "ref_high": self.ref_high,
            "flag": self.flag,
            "date": self.date,
            "source_file": self.source_file,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LabRecord":
        d = d or {}
        v = d.get("value")
        if v is not None and not isinstance(v, (int, float)):
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = None
        return cls(
            marker_name=str(d.get("marker_name") or ""),
            value=v,
            unit=d.get("unit"),
            ref_low=_float_or_none(d.get("ref_low")),
            ref_high=_float_or_none(d.get("ref_high")),
            flag=d.get("flag"),
            date=d.get("date"),
            source_file=d.get("source_file"),
        )


def _float_or_none(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


@dataclass
class AskedQuestionRecord:
    """Вопрос, который уже задавали пользователю."""
    question: str = ""
    asked_at: Optional[str] = None
    answered: bool = False
    answer_summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "asked_at": self.asked_at,
            "answered": self.answered,
            "answer_summary": self.answer_summary,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AskedQuestionRecord":
        d = d or {}
        return cls(
            question=str(d.get("question") or ""),
            asked_at=d.get("asked_at"),
            answered=bool(d.get("answered")),
            answer_summary=d.get("answer_summary"),
        )


@dataclass
class FollowUpPlan:
    """План дальнейших шагов: что спросить, что сдать, что наблюдать."""
    pending_questions: List[str] = field(default_factory=list)
    pending_labs: List[str] = field(default_factory=list)
    monitoring_targets: List[str] = field(default_factory=list)
    next_step: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pending_questions": list(self.pending_questions),
            "pending_labs": list(self.pending_labs),
            "monitoring_targets": list(self.monitoring_targets),
            "next_step": self.next_step,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FollowUpPlan":
        d = d or {}
        return cls(
            pending_questions=list(d.get("pending_questions") or []),
            pending_labs=list(d.get("pending_labs") or []),
            monitoring_targets=list(d.get("monitoring_targets") or []),
            next_step=d.get("next_step"),
        )


@dataclass
class MikhailSessionMemory:
    """Память сессии: симптомы, анализы, заданные вопросы, гипотезы, план follow-up."""
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    symptoms: List[SymptomRecord] = field(default_factory=list)
    labs: List[LabRecord] = field(default_factory=list)
    asked_questions: List[AskedQuestionRecord] = field(default_factory=list)
    hypotheses_history: List[Dict[str, Any]] = field(default_factory=list)
    prior_states: List[str] = field(default_factory=list)
    uploaded_files: List[Dict[str, Any]] = field(default_factory=list)
    follow_up_plan: Optional[FollowUpPlan] = None
    last_summary: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "symptoms": [s.to_dict() for s in self.symptoms],
            "labs": [l.to_dict() for l in self.labs],
            "asked_questions": [q.to_dict() for q in self.asked_questions],
            "hypotheses_history": list(self.hypotheses_history)[-20:],
            "prior_states": list(self.prior_states)[-10:],
            "uploaded_files": list(self.uploaded_files)[-10:],
            "follow_up_plan": self.follow_up_plan.to_dict() if self.follow_up_plan else None,
            "last_summary": self.last_summary,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MikhailSessionMemory":
        d = d or {}
        fp = d.get("follow_up_plan")
        return cls(
            session_id=d.get("session_id"),
            user_id=d.get("user_id"),
            symptoms=[SymptomRecord.from_dict(x) for x in (d.get("symptoms") or [])],
            labs=[LabRecord.from_dict(x) for x in (d.get("labs") or [])],
            asked_questions=[AskedQuestionRecord.from_dict(x) for x in (d.get("asked_questions") or [])],
            hypotheses_history=list(d.get("hypotheses_history") or [])[-20:],
            prior_states=list(d.get("prior_states") or [])[-10:],
            uploaded_files=list(d.get("uploaded_files") or [])[-10:],
            follow_up_plan=FollowUpPlan.from_dict(fp) if fp else None,
            last_summary=d.get("last_summary"),
            updated_at=d.get("updated_at"),
        )
