"""
Доменные профили для risk engine.
Каждый профиль считает риск по своему домену на основе values, findings, hypotheses.
Не создаёт новых findings — только оценивает уже согласованные сущности.
"""
from __future__ import annotations

from app.services.clinical_engine.risk_profiles.cardiometabolic import score_cardiometabolic_risk
from app.services.clinical_engine.risk_profiles.hematology import score_hematology_risk
from app.services.clinical_engine.risk_profiles.inflammation import score_inflammation_risk
from app.services.clinical_engine.risk_profiles.endocrine import score_endocrine_risk

__all__ = [
    "score_cardiometabolic_risk",
    "score_hematology_risk",
    "score_inflammation_risk",
    "score_endocrine_risk",
]
