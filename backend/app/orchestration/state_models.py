from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    age: int | None = None
    sex: str | None = None
    pregnancy: bool | None = None


class HistoryState(BaseModel):
    duration: str = ""
    onset: str = ""
    location: str = ""
    severity: str = ""
    temperature: float | None = None
    symptoms: list[str] = Field(default_factory=list)
    chronic_conditions: list[str] = Field(default_factory=list)
    medications: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    lifestyle: list[str] = Field(default_factory=list)


class UploadedFileState(BaseModel):
    file_name: str
    file_type: str
    content_text: str | None = None


class ParsedLabValue(BaseModel):
    analyte_id: str
    name: str
    value: float | None = None
    unit: str = ""
    reference_range: str = ""
    status: Literal["normal", "high", "low", "unknown"] = "unknown"
    panel: str = ""
    confidence_score: float = 0.0
    flag: str | None = None


class RetrievedKnowledgeItem(BaseModel):
    source_type: str
    source_id: str
    content_summary: str
    relevance_hint: str = "medium"
    payload: dict[str, Any] = Field(default_factory=dict)


class RankedKnowledgeItem(BaseModel):
    source_id: str
    source_type: str
    relevance_score: float
    confidence_score: float
    knowledge_summary: str


class HypothesisItem(BaseModel):
    name: str
    likelihood: Literal["high", "medium", "low", "very_low"] = "low"
    supports: list[str] = Field(default_factory=list)
    against: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)


class WeightedHypothesisItem(BaseModel):
    diagnosis: str
    diagnosis_score: float
    symptom_score: float
    lab_score: float
    risk_score: float
    demographic_score: float
    guideline_score: float
    confidence_level: Literal["high", "medium", "low", "uncertain"] = "uncertain"


class NextBestQuestion(BaseModel):
    question: str
    reason: str
    question_type: Literal["red_flag", "differential", "severity", "follow_up"] = "follow_up"
    expected_impact: Literal["high", "medium", "low"] = "medium"


class IntakeOutput(BaseModel):
    chief_complaint: str
    history: HistoryState
    uploaded_files: list[UploadedFileState] = Field(default_factory=list)


class AdaptiveQuestionOutput(BaseModel):
    known_data: dict[str, Any] = Field(default_factory=dict)
    top_hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    red_flags_detected: list[str] = Field(default_factory=list)
    missing_critical_data: list[str] = Field(default_factory=list)
    next_best_question: NextBestQuestion | None = None
    should_stop_questioning: bool = False
    stop_reason: str = ""


class LabParserOutput(BaseModel):
    parsed_labs: list[ParsedLabValue] = Field(default_factory=list)


class RetrievalOutput(BaseModel):
    retrieved_knowledge: list[RetrievedKnowledgeItem] = Field(default_factory=list)


class RankingOutput(BaseModel):
    ranked_knowledge: list[RankedKnowledgeItem] = Field(default_factory=list)


class ReasoningOutput(BaseModel):
    observations: list[str] = Field(default_factory=list)
    differential_hypotheses: list[HypothesisItem] = Field(default_factory=list)
    recommended_questions: list[str] = Field(default_factory=list)
    recommended_tests: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)


class WeightingOutput(BaseModel):
    weighted_hypotheses: list[WeightedHypothesisItem] = Field(default_factory=list)


class SafetyOutput(BaseModel):
    is_safe: bool = True
    urgent_notice: str | None = None
    unsafe_elements_removed: list[str] = Field(default_factory=list)
    final_safety_notes: list[str] = Field(default_factory=list)
    disclaimer: str = ""


class FinalAnswerOutput(BaseModel):
    final_answer: dict[str, Any] = Field(default_factory=dict)


class ConsultationState(BaseModel):
    session_id: str = ""
    user_profile: UserProfile = Field(default_factory=UserProfile)
    chief_complaint: str = ""
    history: HistoryState = Field(default_factory=HistoryState)
    uploaded_files: list[UploadedFileState] = Field(default_factory=list)
    parsed_labs: list[ParsedLabValue] = Field(default_factory=list)
    retrieved_knowledge: list[RetrievedKnowledgeItem] = Field(default_factory=list)
    ranked_knowledge: list[RankedKnowledgeItem] = Field(default_factory=list)
    hypotheses: list[HypothesisItem] = Field(default_factory=list)
    weighted_hypotheses: list[WeightedHypothesisItem] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    next_question: NextBestQuestion | None = None
    safe_recommendations: list[str] = Field(default_factory=list)
    urgent_recommendation: str | None = None
    final_answer: dict[str, Any] | None = None

    # ---- stage1 triage extension (add-only) ----
    case_id: str = ""
    conversation_stage: str = "intake"

    evidence_present: list[str] = Field(default_factory=list)
    evidence_absent: list[str] = Field(default_factory=list)
    evidence_unknown: list[str] = Field(default_factory=list)

    body_regions: list[str] = Field(default_factory=list)
    temporal_markers: list[str] = Field(default_factory=list)
    severity_hints: list[str] = Field(default_factory=list)

    asked_questions: list[str] = Field(default_factory=list)
    next_questions: list[dict[str, Any]] = Field(default_factory=list)

    top_hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    red_flags_detected: list[str] = Field(default_factory=list)
    contradictions: dict[str, Any] = Field(default_factory=dict)

    care_level: str = "undetermined"
    last_clinical_update_reason: str = ""

    # ---- V4 clinical reasoning (CDSS) ----
    diagnosis_candidates: list[dict[str, Any]] = Field(default_factory=list)
    differential_diagnosis: list[dict[str, Any]] = Field(default_factory=list)

    # ---- V5 probabilistic diagnosis ----
    diagnosis_probabilities: list[dict[str, Any]] = Field(default_factory=list)

