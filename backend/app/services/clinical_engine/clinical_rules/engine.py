"""
P1/P2 Clinical Rules Engine: паттерны поверх прямых findings, без замены profile rules.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.clinical_engine.contracts import ClinicalPattern, Finding, LabValue
from app.services.clinical_engine.clinical_rules.p1_patterns import (
    run_glucose_patterns,
    run_hematology_patterns,
    run_inflammation_patterns,
    run_lipid_patterns,
    run_vitamin_patterns,
)
class ClinicalRulesEngine:
    def run(
        self,
        values: Dict[str, LabValue],
        findings: List[Finding],
        patient_meta: Dict[str, Any],
    ) -> List[ClinicalPattern]:
        """Сырые паттерны (порядок модулей); ранжирование — в integration через pattern_ranker."""
        patterns: List[ClinicalPattern] = []
        patterns.extend(run_hematology_patterns(values, findings, patient_meta))
        patterns.extend(run_lipid_patterns(values, findings, patient_meta))
        patterns.extend(run_glucose_patterns(values, findings, patient_meta))
        patterns.extend(run_vitamin_patterns(values, findings, patient_meta))
        patterns.extend(run_inflammation_patterns(values, findings, patient_meta))
        return patterns
