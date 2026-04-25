"""Structured contracts for consultation runtime and future orchestrator."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class HypothesisItem(BaseModel):
    name: str
    likelihood: Literal["high", "moderate", "possible"] = "possible"
    why_it_fits: list[str] = Field(default_factory=list)


class ConsultationStructuredOutput(BaseModel):
    severity: Literal["GREEN", "YELLOW", "RED"] = "YELLOW"
    red_flags_present: bool = False
    chief_complaint: str = ""
    missing_information: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    top_hypotheses: list[HypothesisItem] = Field(default_factory=list)
    recommended_labs: list[str] = Field(default_factory=list)
    care_plan_today: list[str] = Field(default_factory=list)
    when_urgent: list[str] = Field(default_factory=list)
    patient_summary: str = ""
    patient_facing_response: str = ""
    disclaimer: str = ""

    # Safe additive fields for future enrichment layers.
    # They are optional in practice because they default to empty dicts.
    symptom_context: dict[str, Any] = Field(default_factory=dict)
    nutrition_context: dict[str, Any] = Field(default_factory=dict)
    lab_context: dict[str, Any] = Field(default_factory=dict)


CONSULTATION_JSON_SCHEMA: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "consultation_structured_output",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "severity": {"type": "string", "enum": ["GREEN", "YELLOW", "RED"]},
                "red_flags_present": {"type": "boolean"},
                "chief_complaint": {"type": "string"},
                "missing_information": {"type": "array", "items": {"type": "string"}},
                "follow_up_questions": {"type": "array", "items": {"type": "string"}},
                "top_hypotheses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "name": {"type": "string"},
                            "likelihood": {
                                "type": "string",
                                "enum": ["high", "moderate", "possible"],
                            },
                            "why_it_fits": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["name", "likelihood", "why_it_fits"],
                    },
                },
                "recommended_labs": {"type": "array", "items": {"type": "string"}},
                "care_plan_today": {"type": "array", "items": {"type": "string"}},
                "when_urgent": {"type": "array", "items": {"type": "string"}},
                "patient_summary": {"type": "string"},
                "patient_facing_response": {"type": "string"},
                "disclaimer": {"type": "string"},

                # New safe additive context objects.
                # Using generic objects here avoids schema breakage
                # while keeping strict top-level output.
                "symptom_context": {
                    "type": "object",
                    "additionalProperties": True,
                },
                "nutrition_context": {
                    "type": "object",
                    "additionalProperties": True,
                },
                "lab_context": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
            "required": [
                "severity",
                "red_flags_present",
                "chief_complaint",
                "missing_information",
                "follow_up_questions",
                "top_hypotheses",
                "recommended_labs",
                "care_plan_today",
                "when_urgent",
                "patient_summary",
                "patient_facing_response",
                "disclaimer",
                "symptom_context",
                "nutrition_context",
                "lab_context",
            ],
        },
    },
}


class ConsultationStateSnapshot(BaseModel):
    """Preparation for the stateful orchestrator introduced in the next phase."""

    complaint: str = ""
    protocol_source: str = "general"
    severity: Literal["GREEN", "YELLOW", "RED"] = "YELLOW"
    required_fields: list[str] = Field(default_factory=list)
    collected_facts: dict[str, str] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    last_follow_up_question: Optional[str] = None
    can_conclude: bool = False
    suggested_labs: list[str] = Field(default_factory=list)
    nutrition_recommendations: list[str] = Field(default_factory=list)
    physical_exercise_prevention_rehabilitation: list[str] = Field(default_factory=list)
    dialogue_meta: dict[str, object] = Field(default_factory=dict)
    labs_meta: dict[str, object] = Field(default_factory=dict)
    seasonality: dict[str, object] = Field(default_factory=dict)
    market_signal_cluster: str = ""
    public_source_basis: list[str] = Field(default_factory=list)

    # New additive state fields for enrichment pipeline.
    symptom_context: dict[str, Any] = Field(default_factory=dict)
    nutrition_context: dict[str, Any] = Field(default_factory=dict)
    lab_context: dict[str, Any] = Field(default_factory=dict)

    # Case state for stateful triage (Stage 1)
    case_state: Optional[dict[str, Any]] = None


@dataclass
class BranchConsultationResult:
    matched: bool
    branch_name: str
    relevance_score: float = 0.0
    patient_safe_text: str = ""
    doctor_safe_json: dict[str, Any] = field(default_factory=dict)
    care_level: str = ""
    followup_questions: list[str] = field(default_factory=list)
    machine_payload: dict[str, Any] = field(default_factory=dict)
    branch_memory: Any | None = None
    errors: list[str] = field(default_factory=list)