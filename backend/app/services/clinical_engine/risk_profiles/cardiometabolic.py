"""
Кардиометаболический риск: липиды, глюкоза/фруктозамин, воспаление (hs-CRP).
Использует только normalized values, final findings, working hypotheses.
"""
from __future__ import annotations

from typing import List

from app.services.clinical_engine.contracts import Finding, LabValue, RiskAssessment


def _val(values: List[LabValue], code: str) -> LabValue | None:
    for v in values:
        if v.code == code:
            return v
    return None


def score_cardiometabolic_risk(
    values: List[LabValue],
    findings: List[Finding],
    hypotheses: List[str],
) -> RiskAssessment:
    """
    Правила:
    - LDL > 5.0 или total_cholesterol > 7.0 → сильный драйвер, high risk при достаточном score.
    - Фруктозамин выше референса → дополнительный фактор.
    - ApoB/non-HDL high, семейная гипотеза → усиление.
    - hs-CRP низкий, ТГ нормальные, HbA1c нормальный → не отменяют высокий риск, но снижают срочность (отмечаем отсутствие острого воспаления).
    """
    score = 0.0
    rationale: List[str] = []
    drivers: List[str] = []

    ldl = _val(values, "ldl_cholesterol")
    total = _val(values, "total_cholesterol")
    fruct = _val(values, "fructosamine")
    hs_crp = _val(values, "hs_crp") or _val(values, "crp")
    tg = _val(values, "triglycerides")
    hba1c = _val(values, "hba1c")
    apo_b = _val(values, "apo_b")

    # Сильные драйверы
    if ldl and ldl.value is not None:
        if ldl.value > 5.0:
            score += 4
            rationale.append(f"ЛПНП {ldl.value:.2f} ммоль/л значительно выше целевого")
            drivers.append("marked_ldl_elevation")
        elif ldl.value > 3.0:
            score += 2
            rationale.append("ЛПНП выше целевого диапазона")

    if total and total.value is not None:
        if total.value > 7.0:
            score += 3
            rationale.append(f"Общий холестерин {total.value:.2f} ммоль/л значительно повышен")
            drivers.append("severe_hypercholesterolemia")
        elif total.value > 6.0:
            score += 1
            rationale.append("Общий холестерин выше референса")

    # Дополнительные факторы по findings
    finding_codes = {f.code for f in findings}
    if "severe_hypercholesterolemia" in finding_codes or "marked_ldl_elevation" in finding_codes:
        if "marked_ldl_elevation" not in drivers and ldl and ldl.value is not None and ldl.value > 5.0:
            drivers.append("marked_ldl_elevation")
        if "severe_hypercholesterolemia" not in drivers and total and total.value is not None and total.value > 7.0:
            drivers.append("severe_hypercholesterolemia")

    # ApoB / non-HDL
    if apo_b and apo_b.value is not None and apo_b.ref_high is not None and apo_b.value > apo_b.ref_high:
        score += 1
        rationale.append("Аполипопротеин B выше референса")
        drivers.append("apo_b_high")

    # Семейная гипотеза
    hypo_lower = " ".join(hypotheses).lower()
    if "семейн" in hypo_lower or "гиперхолестеринеми" in hypo_lower:
        score += 0.5
        rationale.append("Учтена гипотеза первичной/семейной гиперхолестеринемии")

    # Фруктозамин — дополнительный фактор
    if fruct and fruct.value is not None and fruct.ref_high is not None and fruct.value > fruct.ref_high:
        score += 1
        rationale.append("Фруктозамин выше референса — уточнение углеводного обмена")
        drivers.append("fructosamine_elevated")

    # Уровень по score
    if score >= 6:
        level = "high"
        label = "Высокий кардиометаболический риск"
    elif score >= 3:
        level = "moderate"
        label = "Умеренный кардиометаболический риск"
    else:
        level = "low"
        label = "Низкий кардиометаболический риск"

    recommended_actions = [
        "Оценка сердечно-сосудистого риска",
        "Повторная липидограмма натощак",
        "ApoB / non-HDL-C",
        "ТТГ",
    ]
    if fruct and fruct.value is not None and fruct.ref_high is not None and fruct.value > fruct.ref_high:
        recommended_actions.extend(["Глюкоза натощак", "Инсулин / HOMA-IR по показаниям"])

    return RiskAssessment(
        domain="cardiometabolic_risk",
        level=level,
        score=score,
        label=label,
        rationale=rationale,
        drivers=drivers,
        recommended_actions=recommended_actions,
    )


def get_cardiometabolic_risk_note(
    values: List[LabValue],
    assessment: RiskAssessment,
) -> str:
    """
    Короткая заметка для summary_text: что снижает срочность (hs-CRP низкий и т.д.).
    Не отменяет высокий риск, но поясняет отсутствие острого воспаления.
    """
    parts: List[str] = []
    hs_crp = _val(values, "hs_crp") or _val(values, "crp")
    if hs_crp and hs_crp.value is not None and hs_crp.value < 1.0:
        parts.append("Признаков выраженного воспалительного сигнала по hs-CRP нет.")
    return " ".join(parts).strip()
