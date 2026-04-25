"""
Воспалительные маркеры. P1.
CRP, hs-CRP, СОЭ, прокальцитонин при наличии.
Скелет: в разработке; CRP частично в биохимии.
"""
from __future__ import annotations

from app.services.clinical_engine.profile_registry import P1_HIGH_VALUE
from app.services.clinical_engine.profiles.base import BaseProfileSkeleton


class InflammationPanelProfile(BaseProfileSkeleton):
    profile_key = "inflammation_panel"
    document_type = "biochemistry_blood"
    priority = P1_HIGH_VALUE

    def build_group_interpretation(self, values, findings):
        return [
            {"group": "Воспаление", "markers": ["crp", "hs_crp", "esr", "pct"], "interpretation": "Профиль в разработке."},
        ]
