"""
B12 / фолат / гомоцистеин. P2.
Скелет: в разработке; гомоцистеин частично в биохимии.
"""
from __future__ import annotations

from app.services.clinical_engine.profile_registry import P2_CLINICALLY_STRONG
from app.services.clinical_engine.profiles.base import BaseProfileSkeleton


class B12FolatePanelProfile(BaseProfileSkeleton):
    profile_key = "b12_folate_panel"
    document_type = "biochemistry_blood"
    priority = P2_CLINICALLY_STRONG

    def build_group_interpretation(self, values, findings):
        return [
            {"group": "B12 / фолат / гомоцистеин", "markers": ["b12", "folate", "homocysteine", "mma"], "interpretation": "Профиль в разработке."},
        ]
