"""
Базовый класс для скелетов профилей: общие заглушки и контракт.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.clinical_engine.contracts import Finding, OverallRisk
from app.services.clinical_engine.profile_contract import ClinicalProfile


class BaseProfileSkeleton(ClinicalProfile):
    """
    Скелет профиля: все методы по умолчанию возвращают пустые/нейтральные значения.
    Реальные профили переопределяют extract_values + build_*.
    """

    def extract_values(self, text: str) -> Any:
        return {}

    def build_findings(self, values: Any) -> List[Finding]:
        return []

    def build_group_interpretation(self, values: Any, findings: List[Finding]) -> List[Dict[str, Any]]:
        return [{"group": "Общие показатели", "markers": [], "interpretation": "Данный профиль пока в разработке."}]

    def build_hypotheses(self, values: Any, findings: List[Finding]) -> List[str]:
        return ["Интерпретация профиля в разработке. Покажите анализ врачу."]

    def build_next_steps(self, values: Any, findings: List[Finding]) -> List[Dict[str, Any]]:
        return [
            {"direction": "Общее", "check": "Очная интерпретация врачом", "why": "Профиль в разработке", "priority": "средний"},
        ]

    def build_risk(self, values: Any, findings: List[Finding], hypotheses: List[str]) -> Optional[OverallRisk]:
        from app.services.clinical_engine.contracts import RiskAssessment
        return OverallRisk(
            overall_level="low",
            overall_score=0.0,
            primary_domain="general",
            domain_risks=[
                RiskAssessment(
                    domain="general",
                    level="low",
                    score=0.0,
                    label="Риск не оценивался",
                    rationale=["Профиль в разработке."],
                    drivers=[],
                    recommended_actions=[],
                ),
            ],
            summary_text="Оценка риска по данному профилю пока не реализована.",
            urgency="non_urgent",
        )
