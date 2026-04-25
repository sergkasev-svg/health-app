"""
Печёночный профиль. P1.
АЛТ, АСТ, ГГТ, ЩФ, билирубин общий/прямой, альбумин.
Скелет: базовая биохимия частично покрывает; отдельный профиль — в разработке.
"""
from __future__ import annotations

from app.services.clinical_engine.profile_registry import P1_HIGH_VALUE
from app.services.clinical_engine.profiles.base import BaseProfileSkeleton


class LiverPanelProfile(BaseProfileSkeleton):
    profile_key = "liver_panel"
    document_type = "biochemistry_blood"
    priority = P1_HIGH_VALUE

    def build_group_interpretation(self, values, findings):
        return [
            {"group": "Печень", "markers": ["alt", "ast", "ggt", "alp", "bilirubin_total", "bilirubin_direct", "albumin"], "interpretation": "Профиль в разработке."},
        ]
