"""
Модели врачебного отчёта: только клинически релевантные данные, без user-facing текста.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PatientInfo:
    age: Optional[int] = None
    sex: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"age": self.age, "sex": self.sex}


@dataclass
class SymptomSummary:
    key_symptoms: List[str] = field(default_factory=list)
    duration: Optional[str] = None
    progression: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key_symptoms": self.key_symptoms,
            "duration": self.duration,
            "progression": self.progression,
        }


@dataclass
class LabFinding:
    marker: str = ""
    value: Optional[float] = None
    unit: Optional[str] = None
    flag: Optional[str] = None
    interpretation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "marker": self.marker,
            "value": self.value,
            "unit": self.unit,
            "flag": self.flag,
            "interpretation": self.interpretation,
        }


@dataclass
class ClinicalAssessment:
    main_hypotheses: List[str] = field(default_factory=list)
    supporting_evidence: List[str] = field(default_factory=list)
    differential: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "main_hypotheses": self.main_hypotheses,
            "supporting_evidence": self.supporting_evidence,
            "differential": self.differential,
        }


@dataclass
class ClinicalPlan:
    recommended_tests: List[str] = field(default_factory=list)
    referrals: List[str] = field(default_factory=list)
    follow_up: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommended_tests": self.recommended_tests,
            "referrals": self.referrals,
            "follow_up": self.follow_up,
        }


@dataclass
class PhysicianReport:
    patient_info: PatientInfo = field(default_factory=PatientInfo)
    symptoms: SymptomSummary = field(default_factory=SymptomSummary)
    labs: List[LabFinding] = field(default_factory=list)
    assessment: ClinicalAssessment = field(default_factory=ClinicalAssessment)
    plan: ClinicalPlan = field(default_factory=ClinicalPlan)
    red_flags: List[str] = field(default_factory=list)
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "patient_info": self.patient_info.to_dict(),
            "symptoms": self.symptoms.to_dict(),
            "labs": [l.to_dict() for l in self.labs],
            "assessment": self.assessment.to_dict(),
            "plan": self.plan.to_dict(),
            "red_flags": self.red_flags,
            "notes": self.notes,
        }
