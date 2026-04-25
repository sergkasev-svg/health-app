"""
Профиль железного обмена. P1.
Ферритин, сывороточное железо, трансферрин, ОЖСС/ЛЖСС, насыщение трансферрина.
Скелет: извлечение и правила — в разработке.
"""
from __future__ import annotations

from app.services.clinical_engine.profile_registry import P1_HIGH_VALUE
from app.services.clinical_engine.profiles.base import BaseProfileSkeleton


class IronPanelProfile(BaseProfileSkeleton):
    profile_key = "iron_panel"
    document_type = "biochemistry_blood"
    priority = P1_HIGH_VALUE

    def build_group_interpretation(self, values, findings):
        return [
            {"group": "Железный обмен", "markers": ["ferritin", "serum_iron", "transferrin", "tibc", "tsat"], "interpretation": "Профиль в разработке."},
        ]
