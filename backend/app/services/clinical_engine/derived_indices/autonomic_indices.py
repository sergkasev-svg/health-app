"""
Вегетативный индекс Кердо (адаптация формулы из методички).

Используем вариант: ИК = (1 − ДАД/ЧСС) × 100 при наличии ДАД и ЧСС
(даёт порядок величины, согласуемый с примером: ДАД 67, ЧСС 60 → ≈ −11.7).

Интерпретация — ориентировочная, exploratory.
"""
from __future__ import annotations

from typing import List

from app.services.clinical_engine.derived_indices.contract import DerivedIndex
from app.services.clinical_engine.derived_indices.vitals import VitalsSnapshot


def compute_kerdo_index(vitals: VitalsSnapshot) -> DerivedIndex:
    req = ["dbp_mmhg", "heart_rate"]
    miss: List[str] = []
    if vitals.dbp_mmhg is None:
        miss.append("диастолическое АД")
    if vitals.heart_rate is None:
        miss.append("ЧСС")
    if miss:
        return DerivedIndex(
            code="kerdo_vegetative_index",
            title="Вегетативный индекс Кердо (расчётный)",
            required_markers=req,
            missing_markers=miss,
            confidence="exploratory",
            patient_visible=False,
            interpretation="Без полного набора витальных данных индекс не считается.",
            not_calculated_reason="insufficient_data",
        )
    if vitals.heart_rate <= 0:
        return DerivedIndex(
            code="kerdo_vegetative_index",
            title="Вегетативный индекс Кердо (расчётный)",
            required_markers=req,
            missing_markers=["корректная ЧСС"],
            confidence="exploratory",
            not_calculated_reason="invalid_hr",
        )
    ik = (1.0 - vitals.dbp_mmhg / vitals.heart_rate) * 100.0
    # зона «равновесия» ориентировочно около −15…+15 (методичка)
    if -15 <= ik <= 15:
        st = "в пределах ориентировочной зоны баланса"
        interp = "Без грубого вегетативного перекоса по этой оценке; интерпретация только с клиникой."
    elif ik < -15:
        st = "ниже зоны баланса (ориентир)"
        interp = "Ближе к ваготоническому полюсу по авторской схеме; не диагноз."
    else:
        st = "выше зоны баланса (ориентир)"
        interp = "Симпатическая активация не исключается; нужен контекст."
    return DerivedIndex(
        code="kerdo_vegetative_index",
        title="Вегетативный индекс Кердо (расчётный)",
        value=round(ik, 2),
        unit="усл. ед.",
        status=st,
        interpretation=interp,
        required_markers=req,
        confidence="exploratory",
        patient_visible=False,
    )
