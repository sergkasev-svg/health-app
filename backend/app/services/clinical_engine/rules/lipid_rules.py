"""
Клинические правила для липидного профиля.
Findings строятся из значений; связь findings → summary обязательна.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.services.clinical_engine.contracts import Finding, LabValue


def _val(values: List[LabValue], code: str) -> Optional[float]:
    for v in values:
        if v.code == code and v.value is not None:
            return v.value
    return None


def _lv(values: List[LabValue], code: str) -> Optional[LabValue]:
    for v in values:
        if v.code == code:
            return v
    return None


def apply_lipid_rules(values: List[LabValue]) -> List[Finding]:
    """
    Применяет правила липидного профиля.
    - total_cholesterol > 7.0 → severe_hypercholesterolemia (high)
    - ldl_cholesterol > 5.0 → marked_ldl_elevation (high), атерогенный риск
    - ldl > 3.0 → elevated_ldl (moderate; многие РФ-бланки <3,0 ммоль/л)
    - total > 5.2 → elevated_cholesterol (moderate)
    - fructosamine + hba1c обрабатываются в glucose_rules
    """
    findings: List[Finding] = []
    total = _val(values, "total_cholesterol")
    ldl = _val(values, "ldl_cholesterol")
    hdl = _val(values, "hdl_cholesterol")
    tg = _val(values, "triglycerides")

    if total is not None and total > 7.0:
        findings.append(
            Finding(
                code="severe_hypercholesterolemia",
                title="Выраженная гиперхолестеринемия",
                group="lipid",
                severity="high",
                summary_text="Общий холестерин значительно выше референса (выраженная гиперхолестеринемия).",
                physician_comment="Клинически значимая дислипидемия; требуется оценка причин и сердечно-сосудистого риска.",
                supporting_markers=["total_cholesterol"],
                related_values=[f"{total:.2f}"],
                primary_value_code="total_cholesterol",
                supporting_value_codes=[],
                include_in_summary=True,
                include_in_key_table=True,
                include_in_hypotheses=False,
            )
        )

    if ldl is not None and ldl > 5.0:
        findings.append(
            Finding(
                code="marked_ldl_elevation",
                title="Значимое повышение ЛПНП",
                group="lipid",
                severity="high",
                summary_text="ЛПНП значительно повышен; соответствует повышенному атерогенному риску.",
                physician_comment="Требуется дообследование (ApoB, липопротеин(a), ТТГ) и оценка СС-риска.",
                supporting_markers=["ldl_cholesterol"],
                related_values=[f"{ldl:.2f}"],
                primary_value_code="ldl_cholesterol",
                supporting_value_codes=[],
                include_in_summary=True,
                include_in_key_table=True,
                include_in_hypotheses=False,
            )
        )
    elif ldl is not None and ldl > 3.0:
        findings.append(
            Finding(
                code="elevated_ldl",
                title="Повышен ЛПНП",
                group="lipid",
                severity="moderate",
                summary_text="ЛПНП выше референса.",
                physician_comment="Оценка атерогенного риска и факторов образа жизни.",
                supporting_markers=["ldl_cholesterol"],
                related_values=[f"{ldl:.2f}"],
                primary_value_code="ldl_cholesterol",
                supporting_value_codes=[],
                include_in_summary=True,
                include_in_key_table=True,
                include_in_hypotheses=False,
            )
        )

    if total is not None and 5.2 < total <= 7.0:
        findings.append(
            Finding(
                code="elevated_cholesterol",
                title="Повышен общий холестерин",
                group="lipid",
                severity="moderate",
                summary_text="Общий холестерин выше референса.",
                physician_comment="Оценка соотношения LDL/HDL и триглицеридов.",
                supporting_markers=["total_cholesterol"],
                related_values=[f"{total:.2f}"],
                primary_value_code="total_cholesterol",
                supporting_value_codes=[],
                include_in_summary=True,
                include_in_key_table=True,
                include_in_hypotheses=False,
            )
        )

    if hdl is not None and hdl < 1.0:
        findings.append(
            Finding(
                code="low_hdl",
                title="Снижен ЛПВП",
                group="lipid",
                severity="moderate",
                summary_text="ЛПВП ниже желаемого уровня.",
                physician_comment="Может снижать защиту от атеросклероза.",
                supporting_markers=["hdl_cholesterol"],
                related_values=[f"{hdl:.2f}"],
                primary_value_code="hdl_cholesterol",
                supporting_value_codes=[],
                include_in_summary=True,
                include_in_key_table=True,
                include_in_hypotheses=False,
            )
        )

    if tg is not None and tg > 1.7:
        findings.append(
            Finding(
                code="elevated_triglycerides",
                title="Повышенные триглицериды",
                group="lipid",
                severity="moderate",
                summary_text="Триглицериды выше референса.",
                physician_comment="Может указывать на метаболические нарушения.",
                supporting_markers=["triglycerides"],
                related_values=[f"{tg:.2f}"],
                primary_value_code="triglycerides",
                supporting_value_codes=[],
                include_in_summary=True,
                include_in_key_table=True,
                include_in_hypotheses=False,
            )
        )

    la1 = _lv(values, "apo_a1")
    if (
        la1 is not None
        and la1.value is not None
        and la1.ref_high is not None
        and la1.value > la1.ref_high
    ):
        rl, rh = la1.ref_low, la1.ref_high
        ref_s = f"{rl:.2f}–{rh:.2f}" if rl is not None else f"до {rh:.2f}"
        findings.append(
            Finding(
                code="elevated_apoa1_vs_ref",
                title="Повышен апоА1 относительно референса бланка",
                group="lipid",
                severity="moderate",
                summary_text=(
                    f"Аполипопротеин A1 {la1.value:.2f} г/л выше верхней границы, указанной на бланке ({ref_s} г/л)."
                ),
                physician_comment=(
                    "Интерпретация апоА1 — вместе с апоВ, липидной панелью и клиникой; отдельное повышение "
                    "требует сопоставления с методикой лаборатории и сопутствующими факторами."
                ),
                supporting_markers=["apo_a1"],
                related_values=[f"{la1.value:.2f}"],
                primary_value_code="apo_a1",
                supporting_value_codes=[],
                include_in_summary=True,
                include_in_key_table=True,
                include_in_hypotheses=False,
            )
        )

    lb = _lv(values, "apo_b")
    if (
        lb is not None
        and lb.value is not None
        and lb.ref_high is not None
        and lb.value > lb.ref_high
    ):
        findings.append(
            Finding(
                code="elevated_apob_vs_ref",
                title="Повышен апоВ относительно референса бланка",
                group="lipid",
                severity="high",
                summary_text=(
                    f"Аполипопротеин B {lb.value:.2f} г/л выше верхней границы бланка "
                    f"({(f'{lb.ref_low:.2f}–' if lb.ref_low is not None else '')}{lb.ref_high:.2f} г/л)."
                ),
                physician_comment="Согласовать с ЛПНП/non-HDL и кардиориском; целевые уровни задаёт врач.",
                supporting_markers=["apo_b"],
                related_values=[f"{lb.value:.2f}"],
                primary_value_code="apo_b",
                supporting_value_codes=[],
                include_in_summary=True,
                include_in_key_table=True,
                include_in_hypotheses=False,
            )
        )

    if (
        la1 is not None
        and lb is not None
        and la1.value is not None
        and lb.value is not None
        and la1.value > 0
    ):
        ratio = lb.value / la1.value
        if ratio >= 0.65:
            findings.append(
                Finding(
                    code="apob_apoa1_ratio_note",
                    title="Соотношение ApoB/ApoA1",
                    group="lipid",
                    severity="moderate",
                    summary_text=(
                        f"Отношение ApoB/ApoA1 ≈ {ratio:.2f} (апоВ {lb.value:.2f} г/л, апоА1 {la1.value:.2f} г/л). "
                        "Повышенное соотношение часто рассматривают как маркер большей доли атерогенных частиц "
                        "при совместной оценке с липидной панелью и клиническим риском."
                    ),
                    physician_comment=(
                        "Пороговые значения зависят от популяции и лаборатории; решения о терапии — только с врачом."
                    ),
                    supporting_markers=["apo_b", "apo_a1"],
                    related_values=[f"{ratio:.2f}"],
                    primary_value_code="apo_b",
                    supporting_value_codes=["apo_a1"],
                    include_in_summary=True,
                    include_in_key_table=True,
                    include_in_hypotheses=False,
                )
            )

    return findings
