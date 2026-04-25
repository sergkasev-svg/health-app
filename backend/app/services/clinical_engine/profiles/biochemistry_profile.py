"""
Профиль базовой биохимии крови. P0.
Сейчас отчёт собирается через run_blood_biochemistry_pipeline в document_physician_report.
build_legacy_report не используется — маршрут идёт по pipeline; здесь только контракт и приоритет.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.clinical_engine.contracts import Finding, LabValue, OverallRisk
from app.services.clinical_engine.profile_contract import ClinicalProfile
from app.services.clinical_engine.profile_registry import P0_MUST_HAVE


class BiochemistryProfile(ClinicalProfile):
    profile_key = "biochemistry_blood"
    document_type = "biochemistry_blood"
    priority = P0_MUST_HAVE

    def extract_values(self, text: str) -> Any:
        # Реальное извлечение в clinical_engine (classifier + extractor)
        return []

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

    # build_legacy_report не переопределён: pipeline вызывает run_blood_biochemistry_pipeline
