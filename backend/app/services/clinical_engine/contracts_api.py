from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


Priority = Literal["low", "medium", "high", "urgent"]
RiskLevel = Literal["low", "moderate", "high", "urgent"]
Severity = Literal["info", "borderline", "mild", "moderate", "high", "urgent"]


class LabValue(BaseModel):
    code: str
    label: str
    value: Optional[float] = None
    value_text: Optional[str] = None
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    ref_text: Optional[str] = None
    status: str = "unknown"
    source_text: Optional[str] = None


class Finding(BaseModel):
    code: str
    title: str
    group: str
    severity: Severity
    document_id: Optional[str] = None
    primary_marker: Optional[str] = None
    supporting_markers: list[str] = Field(default_factory=list)
    value: Optional[str] = None
    reference: Optional[str] = None
    comment: str = ""
    patient_visible: bool = True
    physician_visible: bool = True
    requires_gating: bool = False
    confidence: float = 1.0


class Hypothesis(BaseModel):
    code: str
    label: str
    confidence: float
    document_id: Optional[str] = None
    patient_visible: bool = False
    physician_visible: bool = True
    requires_confirmation: bool = False


class NextStep(BaseModel):
    domain: str
    what: str
    why: str
    priority: Priority
    patient_visible: bool = True
    physician_visible: bool = True


class DerivedIndex(BaseModel):
    code: str
    title: str
    value: Optional[float] = None
    unit: Optional[str] = None
    status: Optional[str] = None
    interpretation: Optional[str] = None
    required_markers: list[str] = Field(default_factory=list)
    missing_markers: list[str] = Field(default_factory=list)
    confidence: Literal["established", "supportive", "exploratory"] = "supportive"
    patient_visible: bool = False
    physician_visible: bool = True


class RiskAssessment(BaseModel):
    domain: str
    level: RiskLevel
    score: float
    label: str
    rationale: list[str] = Field(default_factory=list)
    drivers: list[str] = Field(default_factory=list)
    summary: str = ""
    recommended_actions: list[str] = Field(default_factory=list)
    patient_visible: bool = True
    physician_visible: bool = True


class SourceDocumentSummary(BaseModel):
    document_id: str
    document_type: str
    material: str
    title: str
    main_conclusion: str
    priority: Priority


class ClinicalCoreResult(BaseModel):
    material: str
    material_confidence: float
    document_type: str
    profile: str
    summary_level: str = "single_document"
    normalized_values: dict[str, LabValue] = Field(default_factory=dict)
    documents: list[SourceDocumentSummary] = Field(default_factory=list)
    final_findings: list[Finding] = Field(default_factory=list)
    group_interpretations: list[dict] = Field(default_factory=list)
    working_hypotheses: list[Hypothesis] = Field(default_factory=list)
    next_steps: list[NextStep] = Field(default_factory=list)
    derived_indices: list[DerivedIndex] = Field(default_factory=list)
    risk: list[RiskAssessment] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    urgency: list[str] = Field(default_factory=list)
    # P1/P2 UI-блоки (если заполнены — serializers используют их вместо сырых findings)
    pattern_summary_headline: str = ""
    pattern_main_conclusion: str = ""
    pattern_attention_items: list[str] = Field(default_factory=list)
    pattern_next_steps_items: list[str] = Field(default_factory=list)


class PatientInfo(BaseModel):
    display_name: Optional[str] = None
    sex: Optional[str] = None
    age: Optional[int] = None


class UISummaryBlock(BaseModel):
    title: str
    headline: str
    subtext: str
    risk_level: RiskLevel


class UIAnalysisItem(BaseModel):
    name: str
    priority: Priority
    badge_text: str


class UIIndexItem(BaseModel):
    label: str
    value: str
    comment: str = ""


class UIBlockPayload(BaseModel):
    summary: UISummaryBlock
    analyses: list[UIAnalysisItem] = Field(default_factory=list)
    attention: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list)
    indices: list[UIIndexItem] = Field(default_factory=list)
    physician_note: Optional[str] = None


class RenderedSection(BaseModel):
    type: Literal["text", "list", "table"]
    title: str
    content: Optional[str] = None
    items: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class RenderedDocument(BaseModel):
    title: str
    subtitle: Optional[str] = None
    sections: list[RenderedSection] = Field(default_factory=list)


class DocumentsPayload(BaseModel):
    physician_report: RenderedDocument
    patient_report: RenderedDocument
    aggregate_report: RenderedDocument


class AggregateClinicalReportPayload(BaseModel):
    report_id: str
    report_type: Literal["aggregate_clinical_report", "clinical_report"]
    generated_at: datetime
    patient: PatientInfo
    core: ClinicalCoreResult
    ui: UIBlockPayload
    documents: DocumentsPayload
    # Полный HTML «Отчёт для врача» (PDF/скачивание); совпадает с UnifiedClinicalPayload.physician_report_html_full
    physician_report_html_full: str = ""
