"""INF-P2-001: нет выраженного воспалительного сигнала (CRP, СОЭ, WBC в норме)."""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.clinical_engine.contracts import ClinicalPattern, Finding, LabValue
from app.services.clinical_engine.clinical_rules._signals import value_is_normal


def run_inflammation_patterns(
    values: Dict[str, LabValue],
    findings: List[Finding],
    patient_meta: Dict[str, Any],
) -> List[ClinicalPattern]:
    _ = findings
    _ = patient_meta
    crp = values.get("crp") or values.get("hs_crp")
    esr = values.get("esr")
    wbc = values.get("wbc")

    if not all(x is not None and x.value is not None for x in (crp, esr, wbc)):
        return []
    if not (value_is_normal(crp) and value_is_normal(esr) and value_is_normal(wbc)):
        return []

    return [
        ClinicalPattern(
            code="no_strong_inflammatory_signal",
            label="Выраженного воспалительного сигнала не получено",
            category="inflammation",
            level="P2",
            priority_score=10,
            confidence=0.82,
            evidence=["crp", "esr", "wbc"],
            rationale="CRP, СОЭ и лейкоциты без значимых отклонений от референса в извлечённых данных.",
            main_for_summary=False,
            patient_visible=False,
            physician_visible=True,
        )
    ]
