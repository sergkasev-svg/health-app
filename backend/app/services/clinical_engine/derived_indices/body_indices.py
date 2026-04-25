"""ИМТ и прочие индексы тела."""
from __future__ import annotations

from typing import List

from app.services.clinical_engine.derived_indices.contract import DerivedIndex
from app.services.clinical_engine.derived_indices.vitals import VitalsSnapshot


def compute_bmi(vitals: VitalsSnapshot) -> DerivedIndex:
    req = ["height_cm", "weight_kg"]
    miss: List[str] = []
    if vitals.height_cm is None:
        miss.append("рост (см)")
    if vitals.weight_kg is None:
        miss.append("масса (кг)")
    if miss:
        return DerivedIndex(
            code="bmi",
            title="ИМТ (индекс массы тела)",
            required_markers=req,
            missing_markers=miss,
            confidence="established",
            patient_visible=True,
            interpretation="ИМТ = масса (кг) / рост (м)². Диапазон 18.5–24.9 часто соответствует нормальному весу (ВОЗ).",
            not_calculated_reason="insufficient_data",
        )
    h_m = vitals.height_cm / 100.0
    bmi = vitals.weight_kg / (h_m * h_m)
    status = "норма (18.5–24.9)"
    if bmi < 18.5:
        status = "ниже 18.5 (недостаточная масса)"
    elif bmi >= 25 and bmi < 30:
        status = "25–29.9 (избыточная масса)"
    elif bmi >= 30:
        status = "≥30 (ожирение)"
    return DerivedIndex(
        code="bmi",
        title="ИМТ (индекс массы тела)",
        value=round(bmi, 2),
        unit="кг/м²",
        status=status,
        interpretation="Ориентир; не заменяет оценку состава тела врачом.",
        required_markers=req,
        confidence="established",
        patient_visible=True,
    )
