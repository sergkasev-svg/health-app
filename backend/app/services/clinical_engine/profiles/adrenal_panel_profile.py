"""
Профиль надпочечников / стресс-ось (кортизол, АКТГ, ДГЭА-S). P2.
Скелет: правила и извлечение — в разработке.
"""
from __future__ import annotations

from app.services.clinical_engine.profile_registry import P2_CLINICALLY_STRONG
from app.services.clinical_engine.profiles.base import BaseProfileSkeleton


class AdrenalPanelProfile(BaseProfileSkeleton):
    profile_key = "adrenal_panel"
    document_type = "biochemistry_blood"
    priority = P2_CLINICALLY_STRONG

    def build_group_interpretation(self, values, findings):
        return [
            {
                "group": "Надпочечниковая ось",
                "markers": ["cortisol", "acth", "dheas"],
                "interpretation": "Профиль в разработке. Интерпретация только врачом.",
            },
        ]
