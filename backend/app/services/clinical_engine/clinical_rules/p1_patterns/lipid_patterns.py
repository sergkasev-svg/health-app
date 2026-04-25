"""LIP-P1-001: атерогенная дислипидемия (ЛПНП↑, non-HDL↑, при поддержке ОХС↑)."""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.clinical_engine.contracts import ClinicalPattern, Finding, LabValue
from app.services.clinical_engine.clinical_rules._signals import value_is_high


def run_lipid_patterns(
    values: Dict[str, LabValue],
    findings: List[Finding],
    patient_meta: Dict[str, Any],
) -> List[ClinicalPattern]:
    _ = findings
    _ = patient_meta
    ldl = values.get("ldl_cholesterol")
    non_hdl = values.get("non_hdl_cholesterol")
    tot = values.get("total_cholesterol")

    if not ldl or not value_is_high(ldl):
        return []

    if non_hdl is not None and value_is_high(non_hdl):
        conf = 0.88
        evidence = ["ldl_cholesterol", "non_hdl_cholesterol"]
        rationale = (
            "Повышение ЛПНП и non-HDL соответствует атерогенному липидному профилю (по данным бланка)."
        )
        if tot is not None and value_is_high(tot):
            conf = min(0.95, conf + 0.03)
            evidence.append("total_cholesterol")
            rationale += " Подтверждается повышением общего холестерина."
    elif tot is not None and value_is_high(tot):
        conf = 0.82
        evidence = ["ldl_cholesterol", "total_cholesterol"]
        rationale = (
            "Повышение ЛПНП и общего холестерина указывает на атерогенные сдвиги липидного профиля "
            "(non-HDL в тексте не найден — интерпретация без него)."
        )
    else:
        return []

    return [
        ClinicalPattern(
            code="atherogenic_dyslipidemia",
            label="Атерогенная дислипидемия",
            category="lipid",
            level="P1",
            priority_score=80,
            confidence=conf,
            evidence=evidence,
            rationale=rationale,
            main_for_summary=True,
            patient_visible=True,
            physician_visible=True,
        )
    ]
