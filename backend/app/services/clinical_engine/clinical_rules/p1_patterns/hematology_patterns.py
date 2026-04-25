"""HEM-P1-001: железодефицитный паттерн (Hb↓ + ферритин↓ + поддержка Hct/MCHC/MCV)."""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.clinical_engine.contracts import ClinicalPattern, Finding, LabValue
from app.services.clinical_engine.clinical_rules._signals import (
    value_is_borderline_low,
    value_is_low,
)


def run_hematology_patterns(
    values: Dict[str, LabValue],
    findings: List[Finding],
    patient_meta: Dict[str, Any],
) -> List[ClinicalPattern]:
    _ = findings
    _ = patient_meta
    hb = values.get("hb")
    ferritin = values.get("ferritin")
    hct = values.get("hct")
    mchc = values.get("mchc")
    mcv = values.get("mcv")

    # Hb↓ + Hct↓ без ферритина в извлечённых значениях — всё равно поднимаем в P1/сводку
    # (иначе краткий вывод «уезжает» только в витамин D, хотя по бланку видна анемия по ОАК).
    if hb and hct and value_is_low(hb) and value_is_low(hct):
        if ferritin is None or getattr(ferritin, "value", None) is None:
            return [
                ClinicalPattern(
                    code="low_hemoglobin_hematocrit_clarify_iron",
                    label="Снижение гемоглобина и гематокрита",
                    category="hematology",
                    level="P1",
                    priority_score=88,
                    confidence=0.78,
                    evidence=["hb", "hct"],
                    rationale=(
                        "Снижение гемоглобина и гематокрита указывает на необходимость очной оценки; "
                        "для уточнения роли железа обычно нужны ферритин и динамика ОАК (по бланку; не диагноз)."
                    ),
                    main_for_summary=True,
                    patient_visible=True,
                    physician_visible=True,
                )
            ]

    if not hb or ferritin is None or ferritin.value is None:
        return []

    ferritin_val = float(ferritin.value)
    if ferritin_val >= 15:
        return []

    if not value_is_low(hb):
        return []

    conf = 0.92
    evidence = ["hb", "ferritin"]
    rationale = (
        "Снижение гемоглобина на фоне низкого ферритина соответствует железодефицитному состоянию "
        "(рабочая интерпретация по бланку, не диагноз)."
    )

    support = []
    if hct is not None and value_is_low(hct):
        support.append("hct")
    if mchc is not None and value_is_low(mchc):
        support.append("mchc")
    if mcv is not None and (value_is_low(mcv) or value_is_borderline_low(mcv)):
        support.append("mcv")

    if support:
        conf = min(0.98, conf + 0.03)
        evidence.extend(support)
        rationale += f" Поддержка: {', '.join(support)}."

    return [
        ClinicalPattern(
            code="iron_deficiency_pattern",
            label="Железодефицитный паттерн",
            category="hematology",
            level="P1",
            priority_score=90,
            confidence=conf,
            evidence=evidence,
            rationale=rationale,
            main_for_summary=True,
            patient_visible=True,
            physician_visible=True,
        )
    ]
