"""
Профиль щитовидной железы. P1.
ТТГ, св. T4, св. T3, АТ-ТПО, АТ-ТГ.
Скелет: в разработке.
"""
from __future__ import annotations

from app.services.clinical_engine.profile_registry import P1_HIGH_VALUE
from app.services.clinical_engine.profiles.base import BaseProfileSkeleton


class ThyroidPanelProfile(BaseProfileSkeleton):
    profile_key = "thyroid_panel"
    document_type = "thyroid_panel"
    priority = P1_HIGH_VALUE

    def build_group_interpretation(self, values, findings):
        return [
            {"group": "Щитовидная железа", "markers": ["tsh", "ft4", "ft3", "at_tpo", "at_tg"], "interpretation": "Профиль в разработке."},
        ]
