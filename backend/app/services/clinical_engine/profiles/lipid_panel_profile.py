"""
Профиль липидного обмена. P0.
Интерпретация через clinical_engine.profiles.lipid_panel (interpret_lipids).
Legacy-отчёт собирается через build_lipid_report в document_physician_report.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.clinical_engine.contracts import Finding, OverallRisk
from app.services.clinical_engine.profile_contract import ClinicalProfile
from app.services.clinical_engine.profile_registry import P0_MUST_HAVE


class LipidPanelProfile(ClinicalProfile):
    profile_key = "lipid_panel"
    document_type = "biochemistry_blood"
    priority = P0_MUST_HAVE

    def extract_values(self, text: str) -> Any:
        return []

    def build_findings(self, values: Any) -> List[Finding]:
        if isinstance(values, list):
            from app.services.clinical_engine.profiles.lipid_panel import interpret_lipids
            return interpret_lipids(values)
        return []

    def build_group_interpretation(self, values: Any, findings: List[Finding]) -> List[Dict[str, Any]]:
        return []

    def build_hypotheses(self, values: Any, findings: List[Finding]) -> List[str]:
        return []

    def build_next_steps(self, values: Any, findings: List[Finding]) -> List[Dict[str, Any]]:
        return []

    def build_risk(self, values: Any, findings: List[Finding], hypotheses: List[str]) -> Optional[OverallRisk]:
        return None
