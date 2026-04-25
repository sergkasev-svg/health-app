"""
Профиль ОАК (CBC). P0.
Адаптер к существующему cbc_engine: build_legacy_report делегирует в build_cbc_report.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.clinical_engine.contracts import Finding, OverallRisk
from app.services.clinical_engine.profile_contract import ClinicalProfile
from app.services.clinical_engine.profile_registry import P0_MUST_HAVE


class CBCProfile(ClinicalProfile):
    profile_key = "cbc"
    document_type = "cbc"
    priority = P0_MUST_HAVE

    def extract_values(self, text: str) -> Any:
        from app.services.lab_value_extractor import extract_cbc_values
        return extract_cbc_values(text)

    def build_findings(self, values: Any) -> List[Finding]:
        # Пока не конвертируем в Finding; движок CBC отдаёт legacy напрямую
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
        from app.services.cbc_engine import build_cbc_report
        doc = {"extracted_text": extracted_text, "filename": filename}
        return build_cbc_report(doc=doc, extracted_text=extracted_text, profile=None)
