"""
Правила по углеводному обмену: фруктозамин при нормальном HbA1c.
"""
from __future__ import annotations

from typing import List, Optional

from app.services.clinical_engine.contracts import Finding, LabValue


def _val(values: List[LabValue], code: str) -> Optional[float]:
    for v in values:
        if v.code == code and v.value is not None:
            return v.value
    return None


# Референс фруктозамина 205–285 мкмоль/л
FRUCTOSAMINE_REF_HIGH = 285
HBA1C_REF_HIGH = 6.0


def apply_glucose_rules(values: List[LabValue]) -> List[Finding]:
    """
    fructosamine > upper_ref при нормальном HbA1c →
    finding: fructosamine_elevated_with_normal_hba1c (mild).
    """
    findings: List[Finding] = []
    fructosamine = _val(values, "fructosamine")
    hba1c = _val(values, "hba1c")

    if fructosamine is None:
        return findings
    if fructosamine <= FRUCTOSAMINE_REF_HIGH:
        return findings
    # Фруктозамин повышен
    if hba1c is not None and hba1c <= HBA1C_REF_HIGH:
        findings.append(
            Finding(
                code="fructosamine_elevated_with_normal_hba1c",
                title="Повышен фруктозамин при нормальном HbA1c",
                group="glucose",
                severity="mild",
                summary_text="Фруктозамин выше референса при нормальном HbA1c; возможны недавние колебания гликемии.",
                physician_comment="HbA1c в норме. Требуется сопоставление с глюкозой натощак и клиническим контекстом; по показаниям — инсулин, HOMA-IR.",
                supporting_markers=["fructosamine", "hba1c"],
                related_values=[f"{fructosamine:.2f}"],
                primary_value_code="fructosamine",
                supporting_value_codes=["hba1c"],
                include_in_summary=True,
                include_in_key_table=True,
                include_in_hypotheses=False,
            )
        )
    else:
        findings.append(
            Finding(
                code="fructosamine_elevated",
                title="Повышен фруктозамин",
                group="glucose",
                severity="mild",
                summary_text="Фруктозамин выше референса.",
                physician_comment="Оценка углеводного обмена в динамике.",
                supporting_markers=["fructosamine"],
                related_values=[f"{fructosamine:.2f}"],
                primary_value_code="fructosamine",
                supporting_value_codes=[],
                include_in_summary=True,
                include_in_key_table=True,
                include_in_hypotheses=False,
            )
        )
    return findings
