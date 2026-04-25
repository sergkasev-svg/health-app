"""
Профиль аминокислот / метаболических панелей. P3.
Скелет: нишевый профиль, расширение после ядра P0–P2.
"""
from __future__ import annotations

from app.services.clinical_engine.profile_registry import P3_NICHE
from app.services.clinical_engine.profiles.base import BaseProfileSkeleton


class AminoAcidsPanelProfile(BaseProfileSkeleton):
    profile_key = "amino_acids_panel"
    document_type = "generic_lab_document"
    priority = P3_NICHE

    def build_group_interpretation(self, values, findings):
        return [
            {
                "group": "Аминокислотный профиль",
                "markers": [],
                "interpretation": "Профиль в разработке. Нишевое исследование — очная интерпретация врачом.",
            },
        ]
