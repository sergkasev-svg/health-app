"""
Риск по маркерам воспаления (CRP, hs-CRP и др.).
Заглушка: при необходимости отдельного домена воспаления — расширить.
"""
from __future__ import annotations

from typing import List

from app.services.clinical_engine.contracts import Finding, LabValue, RiskAssessment


def score_inflammation_risk(
    values: List[LabValue],
    findings: List[Finding],
    hypotheses: List[str],
) -> RiskAssessment:
    """Пока низкий риск; при высоком CRP/hs-CRP можно поднимать level и добавлять rationale."""
    return RiskAssessment(
        domain="inflammatory_risk",
        level="low",
        score=0.0,
        label="Воспалительный риск не выделен (учтён в кардиометаболическом при необходимости)",
        rationale=[],
        drivers=[],
        recommended_actions=[],
    )
