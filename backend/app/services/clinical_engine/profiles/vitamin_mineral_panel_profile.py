"""
Минеральный и костный обмен. P2.
Кальций, фосфор, магний, витамин D, ПТГ.
Скелет: в разработке.
"""
from __future__ import annotations

from app.services.clinical_engine.profile_registry import P2_CLINICALLY_STRONG
from app.services.clinical_engine.profiles.base import BaseProfileSkeleton


class VitaminMineralPanelProfile(BaseProfileSkeleton):
    profile_key = "vitamin_mineral_panel"
    document_type = "biochemistry_blood"
    priority = P2_CLINICALLY_STRONG

    def build_group_interpretation(self, values, findings):
        return [
            {"group": "Минералы и витамины", "markers": ["calcium", "phosphorus", "magnesium", "vitamin_d", "pth"], "interpretation": "Профиль в разработке."},
        ]
