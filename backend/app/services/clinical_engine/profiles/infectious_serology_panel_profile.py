"""
Профиль инфекционной серологии (EBV, CMV, TORCH, гепатиты и т.д.). P3.
Скелет: клинический контекст обязателен.
"""
from __future__ import annotations

from app.services.clinical_engine.profile_registry import P3_NICHE
from app.services.clinical_engine.profiles.base import BaseProfileSkeleton


class InfectiousSerologyPanelProfile(BaseProfileSkeleton):
    profile_key = "infectious_serology_panel"
    document_type = "generic_lab_document"
    priority = P3_NICHE

    def build_group_interpretation(self, values, findings):
        return [
            {
                "group": "Инфекционная серология",
                "markers": [],
                "interpretation": "Профиль в разработке. Соотнесение с клиникой и эпидемиологией — задача врача.",
            },
        ]
