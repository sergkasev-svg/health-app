"""
Профиль lipid_panel: интерпретация липидного и углеводного обмена.
Вызывается из pipeline при document_type = biochemistry_blood и наличии липидных маркеров.
"""
from __future__ import annotations

from typing import List

from app.services.clinical_engine.contracts import Finding, LabValue
from app.services.clinical_engine.rules import apply_glucose_rules, apply_lipid_rules


def interpret_lipids(values: List[LabValue]) -> List[Finding]:
    """Применяет lipid + glucose rules. Спека: interpret_lipids(values) -> list[Finding]."""
    findings: List[Finding] = []
    findings.extend(apply_lipid_rules(values))
    findings.extend(apply_glucose_rules(values))
    return findings
