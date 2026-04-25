"""
Риск по гематологии (анемия, отклонения ОАК).
Заглушка: при появлении CBC-профиля будет заполнено.
"""
from __future__ import annotations

from typing import List

from app.services.clinical_engine.contracts import Finding, LabValue, RiskAssessment


def score_hematology_risk(
    values: List[LabValue],
    findings: List[Finding],
    hypotheses: List[str],
) -> RiskAssessment:
    """Пока возвращаем низкий риск; при подключении CBC — логика по гемоглобину, эритроцитам, MCV и т.д."""
    return RiskAssessment(
        domain="hematology_risk",
        level="low",
        score=0.0,
        label="Гематологический риск не оценивался (профиль не CBC)",
        rationale=[],
        drivers=[],
        recommended_actions=[],
    )
