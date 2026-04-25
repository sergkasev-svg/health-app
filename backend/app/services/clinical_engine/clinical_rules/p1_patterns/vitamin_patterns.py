"""VIT-P1-001: недостаточность витамина D 20–30 нг/мл."""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.clinical_engine.contracts import ClinicalPattern, Finding, LabValue


def run_vitamin_patterns(
    values: Dict[str, LabValue],
    findings: List[Finding],
    patient_meta: Dict[str, Any],
) -> List[ClinicalPattern]:
    _ = findings
    _ = patient_meta
    v = values.get("vitamin_d_25oh")
    if not v or v.value is None:
        return []
    x = float(v.value)
    if 20.0 <= x < 30.0:
        return [
            ClinicalPattern(
                code="vitamin_d_insufficiency",
                label="Недостаточность витамина D",
                category="vitamin",
                level="P1",
                priority_score=45,
                confidence=0.9,
                evidence=["vitamin_d_25oh"],
                rationale="Уровень 25(OH)D 20–30 нг/мл соответствует недостаточности (ориентир; уточнить референс лаборатории).",
                main_for_summary=False,
                patient_visible=True,
                physician_visible=True,
            )
        ]
    return []
