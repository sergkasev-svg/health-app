"""
Risk scoring layer поверх согласованных сущностей: values, findings, hypotheses.
Не парсит PDF, не создаёт новых findings. Только оценивает клиническую значимость
и приоритизирует next steps.
"""
from __future__ import annotations

from typing import List

from app.services.clinical_engine.contracts import Finding, LabValue, OverallRisk, RiskAssessment
from app.services.clinical_engine.risk_profiles import (
    score_cardiometabolic_risk,
    score_endocrine_risk,
    score_hematology_risk,
    score_inflammation_risk,
)
from app.services.clinical_engine.risk_profiles.cardiometabolic import get_cardiometabolic_risk_note

LEVEL_ORDER = ("low", "moderate", "high", "urgent")


def _level_rank(level: str) -> int:
    try:
        return LEVEL_ORDER.index(level.lower())
    except ValueError:
        return 0


def run_risk_engine(
    values: List[LabValue],
    findings: List[Finding],
    working_hypotheses: List[str],
    profile: str,
    document_type: str,
) -> OverallRisk:
    """
    Вход: только normalized values, final findings, working hypotheses, profile, document_type.
    Выход: OverallRisk с domain_risks, overall_level, summary_text, urgency.
    Urgency отдельно от risk level: high risk ≠ emergent.
    """
    domain_risks: List[RiskAssessment] = []

    if profile in ("lipid_panel", "biochemistry_blood") or document_type in ("biochemistry_blood", "lipid_panel"):
        cardio = score_cardiometabolic_risk(values, findings, working_hypotheses)
        domain_risks.append(cardio)
        # Опционально воспаление/эндокринка как контекст (пока заглушки дают low)
        infl = score_inflammation_risk(values, findings, working_hypotheses)
        if infl.score > 0 or infl.rationale:
            domain_risks.append(infl)
        endo = score_endocrine_risk(values, findings, working_hypotheses)
        if endo.score > 0 or endo.rationale:
            domain_risks.append(endo)

    if profile in ("cbc", "cbc_with_reticulocytes") or "cbc" in (document_type or "").lower():
        hemo = score_hematology_risk(values, findings, working_hypotheses)
        domain_risks.append(hemo)

    # Если ни один домен не запускался — один нейтральный домен
    if not domain_risks:
        domain_risks.append(
            RiskAssessment(
                domain="general",
                level="low",
                score=0.0,
                label="Риск не оценивался по данному профилю",
                rationale=[],
                drivers=[],
                recommended_actions=[],
            )
        )

    # Overall: по максимальному уровню и максимальному score
    primary = max(domain_risks, key=lambda r: (r.score, _level_rank(r.level)))
    overall_level = max(
        (r.level for r in domain_risks),
        key=lambda l: _level_rank(l),
    )
    overall_score = max(r.score for r in domain_risks)

    # Summary text: основной домен + компактные драйверы + дополнительный фактор (фруктозамин) + заметка про hs-CRP
    summary_parts: List[str] = []
    if primary.domain == "cardiometabolic_risk" and primary.rationale:
        summary_parts.append(primary.label + ". ")
        total_v = next((v for v in values if v.code == "total_cholesterol" and v.value is not None), None)
        ldl_v = next((v for v in values if v.code == "ldl_cholesterol" and v.value is not None), None)
        if total_v and ldl_v:
            summary_parts.append(f"Основные драйверы: общий холестерин {total_v.value:.2f} ммоль/л и ЛПНП {ldl_v.value:.2f} ммоль/л. ")
        else:
            summary_parts.append("Основные драйверы: " + "; ".join(primary.rationale[:3]) + ". ")
        if "fructosamine_elevated" in primary.drivers:
            summary_parts.append("Повышенный фруктозамин — дополнительный фактор, требующий уточнения углеводного обмена. ")
        note = get_cardiometabolic_risk_note(values, primary)
        if note:
            summary_parts.append(note)
    else:
        summary_parts.append(primary.label)
        if primary.rationale:
            summary_parts.append(" " + "; ".join(primary.rationale[:3]))

    summary_text = "".join(summary_parts).strip() or f"Общий уровень риска: {overall_level}."

    # Urgency: для липидного/биохимического профиля высокий риск не означает срочность
    urgency = "non_urgent"
    if overall_level == "urgent":
        urgency = "urgent"
    elif overall_level == "high" and primary.domain == "cardiometabolic_risk":
        urgency = "plan_soon"  # запланировать визит, не экстренно

    return OverallRisk(
        overall_level=overall_level,
        overall_score=overall_score,
        primary_domain=primary.domain,
        domain_risks=domain_risks,
        summary_text=summary_text,
        urgency=urgency,
    )


def prioritize_next_steps(
    next_steps: List[dict],
    risk_assessment: OverallRisk | None,
) -> List[dict]:
    """
    Ранжирует next_steps: сначала действия из primary domain risk recommended_actions,
    затем остальные, без дублирования по смыслу (по полю check/what).
    """
    if not risk_assessment or not risk_assessment.domain_risks:
        return next_steps

    primary = next(
        (d for d in risk_assessment.domain_risks if d.domain == risk_assessment.primary_domain),
        None,
    )
    if not primary or not primary.recommended_actions:
        return next_steps

    # Ключи уже существующих шагов (нормализованные для сравнения)
    existing_checks = set()
    for s in next_steps:
        c = (s.get("check") or s.get("what") or "").strip().lower()
        if c:
            existing_checks.add(c)

    # Приоритетные из risk (если ещё не в next_steps — не добавляем новые, только сортируем имеющиеся)
    order_keys: List[str] = [a.strip().lower() for a in primary.recommended_actions if a.strip()]

    def rank(step: dict) -> tuple:
        check = (step.get("check") or step.get("what") or "").strip().lower()
        if not check:
            return (1, 0)
        try:
            idx = next(i for i, k in enumerate(order_keys) if k in check or check in k)
            return (0, idx)
        except StopIteration:
            return (1, 999)

    return sorted(next_steps, key=rank)
