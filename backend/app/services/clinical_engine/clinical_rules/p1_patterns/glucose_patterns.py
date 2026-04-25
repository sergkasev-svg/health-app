"""GLU-P2-001: отсутствие выраженного сигнала по долгосрочной гликемии (HbA1c в норме)."""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.clinical_engine.contracts import ClinicalPattern, Finding, LabValue
from app.services.clinical_engine.clinical_rules._signals import value_is_high, value_is_normal


def run_glucose_patterns(
    values: Dict[str, LabValue],
    findings: List[Finding],
    patient_meta: Dict[str, Any],
) -> List[ClinicalPattern]:
    _ = findings
    _ = patient_meta
    hba1c = values.get("hba1c")
    if not hba1c or hba1c.value is None:
        return []
    if not value_is_normal(hba1c):
        return []
    glu = values.get("glucose") or values.get("fasting_glucose")
    if glu is not None and value_is_high(glu):
        return []

    return [
        ClinicalPattern(
            code="no_diabetic_signal",
            label="Выраженного диабетического сигнала по HbA1c не получено",
            category="glucose",
            level="P2",
            priority_score=15,
            confidence=0.8,
            evidence=["hba1c"],
            rationale="HbA1c в пределах референса — выраженной долгосрочной гипергликемии по этому маркеру не видно.",
            main_for_summary=False,
            patient_visible=False,
            physician_visible=True,
        )
    ]
