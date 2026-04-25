"""
Почечный профиль. P1.
Креатинин, мочевина, eGFR, альбумин/креатинин мочи, белок мочи.
Скелет: в разработке.
"""
from __future__ import annotations

from app.services.clinical_engine.profile_registry import P1_HIGH_VALUE
from app.services.clinical_engine.profiles.base import BaseProfileSkeleton


class KidneyPanelProfile(BaseProfileSkeleton):
    profile_key = "kidney_panel"
    document_type = "biochemistry_blood"
    priority = P1_HIGH_VALUE

    def build_group_interpretation(self, values, findings):
        return [
            {"group": "Функция почек", "markers": ["creatinine", "urea", "egfr", "uacr", "urine_protein"], "interpretation": "Профиль в разработке."},
        ]
