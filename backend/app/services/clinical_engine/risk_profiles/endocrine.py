"""
Риск по эндокринному профилю (ТТГ, углеводный обмен и т.д.).
Заглушка: при появлении thyroid_panel или приоритета эндокринных findings — заполнить.
"""
from __future__ import annotations

from typing import List

from app.services.clinical_engine.contracts import Finding, LabValue, RiskAssessment


def score_endocrine_risk(
    values: List[LabValue],
    findings: List[Finding],
    hypotheses: List[str],
) -> RiskAssessment:
    """Пока низкий риск; при отклонениях ТТГ, выраженной дисгликемии — своя логика."""
    return RiskAssessment(
        domain="endocrine_risk",
        level="low",
        score=0.0,
        label="Эндокринный риск не оценивался отдельно",
        rationale=[],
        drivers=[],
        recommended_actions=[],
    )
