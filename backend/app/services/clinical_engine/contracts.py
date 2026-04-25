"""
Контракты данных clinical engine.
Единый ReportModel и Findings — основа согласованного отчёта.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DocumentType(str, Enum):
    CBC = "cbc"
    CBC_RETIC = "cbc_with_reticulocytes"
    BIOCHEMISTRY_BLOOD = "biochemistry_blood"
    LIPID_PANEL = "lipid_panel"
    THYROID_PANEL = "thyroid_panel"
    URINALYSIS = "urinalysis"
    ORGANIC_ACIDS_URINE = "organic_acids_urine"
    GENERIC_LAB = "generic_lab_document"


class LabValue(BaseModel):
    code: str
    label: str
    value: Optional[float] = None
    value_text: Optional[str] = None
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    ref_text: Optional[str] = None
    status: str = "unknown"  # normal, high, low, borderline_high, borderline_low, critical
    source_text: Optional[str] = None


class Finding(BaseModel):
    code: str
    title: str
    group: str
    severity: str  # high, moderate, mild, info
    summary_text: str
    physician_comment: str
    patient_comment: Optional[str] = None
    supporting_markers: List[str] = Field(default_factory=list)
    related_values: List[str] = Field(default_factory=list)
    primary_value_code: Optional[str] = None
    supporting_value_codes: List[str] = Field(default_factory=list)
    include_in_summary: bool = True
    include_in_key_table: bool = True
    include_in_hypotheses: bool = True
    # UI routing: None = policy default
    patient_visible: Optional[bool] = None
    physician_visible: Optional[bool] = None
    requires_gating: Optional[bool] = None
    confidence: Optional[str] = None  # high / medium / low


class RiskAssessment(BaseModel):
    """Оценка риска по одному домену (кардиометаболический, анемия, воспаление, эндокринный)."""
    domain: str
    level: str  # low / moderate / high / urgent
    score: float = 0.0
    label: str = ""
    rationale: List[str] = Field(default_factory=list)
    drivers: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    patient_visible: bool = True
    physician_visible: bool = True


class ClinicalPattern(BaseModel):
    """
    P1/P2 клинический паттерн: связка маркеров → смысл → приоритет.
    Не заменяет findings; дополняет сводку и внимание врача.
    """

    code: str
    label: str
    category: str  # hematology / lipid / glucose / vitamin / inflammation / ...
    level: str  # P1 (паттерн) / P2 (контекст, фон)
    priority_score: int = 50
    confidence: float = 0.8
    evidence: List[str] = Field(default_factory=list)
    rationale: str = ""
    main_for_summary: bool = False
    patient_visible: bool = False
    physician_visible: bool = True


class Hypothesis(BaseModel):
    """Структурированная рабочая гипотеза (альтернатива списку строк)."""
    code: str = ""
    label: str = ""
    confidence: float = 1.0
    patient_visible: bool = False
    physician_visible: bool = True
    requires_confirmation: bool = False


class NextStep(BaseModel):
    """Структурированный шаг (альтернатива List[Dict] в next_steps)."""
    domain: str = "general"
    what: str = ""
    why: str = ""
    priority: str = "medium"
    patient_visible: bool = True
    physician_visible: bool = True


class OverallRisk(BaseModel):
    """Сводная оценка риска по всем доменам. Urgency отдельно от level (high risk ≠ emergent)."""
    overall_level: str  # low / moderate / high / urgent
    overall_score: float = 0.0
    primary_domain: Optional[str] = None
    domain_risks: List[RiskAssessment] = Field(default_factory=list)
    summary_text: str = ""
    urgency: str = "non_urgent"  # non_urgent / plan_soon / urgent / emergent


class ReportModel(BaseModel):
    document_type: str
    profile: Optional[str] = None
    title: str
    subtitle: str
    summary: str
    key_findings: List[Finding] = Field(default_factory=list)
    borderline_findings: List[Finding] = Field(default_factory=list)
    group_interpretations: List[Dict[str, Any]] = Field(default_factory=list)
    working_hypotheses: List[str] = Field(default_factory=list)
    next_steps: List[Dict[str, Any]] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    urgency: List[str] = Field(default_factory=list)
    raw_values: List[LabValue] = Field(default_factory=list)
    risk_assessment: Optional[OverallRisk] = None

    model_config = ConfigDict(extra="allow")


class ClinicalCoreResult(BaseModel):
    """
    Единый источник правды для отчётов.
    Из него строятся physician report и patient-safe report — только разная подача.

    Расширения unified pipeline: material*, derived_indices, структурированные гипотезы/шаги.
    """
    document_type: str
    profile: str
    normalized_values: Dict[str, LabValue] = Field(default_factory=dict)
    final_findings: List[Finding] = Field(default_factory=list)
    working_hypotheses: List[str] = Field(default_factory=list)
    next_steps: List[Dict[str, Any]] = Field(default_factory=list)
    risk: Optional[OverallRisk] = None
    limitations: List[str] = Field(default_factory=list)
    urgency: List[str] = Field(default_factory=list)
    summary: str = ""
    group_interpretations: List[Dict[str, Any]] = Field(default_factory=list)
    # --- unified clinical pipeline layer ---
    material: str = ""
    material_confidence: float = 0.0
    material_routing_reasons: List[str] = Field(default_factory=list)
    profile_route: str = ""  # явный ключ маршрута (совпадает с profile или report_type)
    derived_indices: List[Dict[str, Any]] = Field(default_factory=list)
    hypotheses_structured: List[Hypothesis] = Field(default_factory=list)
    next_steps_structured: List[NextStep] = Field(default_factory=list)
    # Плоский список доменных рисков (синхронизируется с risk.domain_risks)
    risk_domains: List[RiskAssessment] = Field(default_factory=list)
    # P1/P2 слой: интегрированные клинические паттерны (после прямых findings)
    clinical_patterns: List[ClinicalPattern] = Field(default_factory=list)
    # Структурированный вывод для UI (после summary_builder)
    pattern_summary_headline: str = ""
    pattern_main_conclusion: str = ""
    pattern_attention_items: List[str] = Field(default_factory=list)
    pattern_next_steps_items: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class UIRouteResult(BaseModel):
    """
    Результат UI-level routing: один core → три канала показа.
    Не меняет клинический смысл; только раскладка по видимости.
    """
    patient_summary: str = ""
    patient_findings: List[str] = Field(default_factory=list)
    patient_what_it_means: str = ""
    patient_actions: List[str] = Field(default_factory=list)
    patient_red_flags: List[str] = Field(default_factory=list)
    physician_report: Dict[str, Any] = Field(default_factory=dict)
    gated_sections: List[Dict[str, Any]] = Field(default_factory=list)
    # Мета: какие гипотезы/секции скрыты от пациента (low-confidence или confirmation-dependent)
    gated_hypotheses: List[str] = Field(default_factory=list)
    gated_reasoning: List[str] = Field(default_factory=list)
