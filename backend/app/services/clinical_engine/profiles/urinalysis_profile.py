"""
Профиль ОАМ (Urinalysis). P0.
Адаптер к urinalysis_engine: build_legacy_report делегирует в build_urinalysis_report.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.clinical_engine.contracts import Finding, OverallRisk
from app.services.clinical_engine.profile_contract import ClinicalProfile
from app.services.clinical_engine.profile_registry import P0_MUST_HAVE


class UrinalysisProfile(ClinicalProfile):
    profile_key = "urinalysis"
    document_type = "urinalysis"
    priority = P0_MUST_HAVE

    def extract_values(self, text: str) -> Any:
        from app.services.urinalysis_engine import extract_urine_values
        return extract_urine_values(text)

    def build_findings(self, values: Any) -> List[Finding]:
        return []

    def build_group_interpretation(self, values: Any, findings: List[Finding]) -> List[Dict[str, Any]]:
        return []

    def build_hypotheses(self, values: Any, findings: List[Finding]) -> List[str]:
        return []

    def build_next_steps(self, values: Any, findings: List[Finding]) -> List[Dict[str, Any]]:
        return []

    def build_risk(self, values: Any, findings: List[Finding], hypotheses: List[str]) -> Optional[OverallRisk]:
        return None

    def build_legacy_report(self, extracted_text: str, filename: str = "") -> Optional[Dict[str, Any]]:
        from app.services.urinalysis_engine import build_urinalysis_report
        return build_urinalysis_report(extracted_text, filename)
