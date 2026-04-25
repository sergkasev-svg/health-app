"""
Органические кислоты мочи. P3.
Отдельный pipeline (organic_acids_route); здесь только контракт для registry.
"""
from __future__ import annotations

from app.services.clinical_engine.profile_registry import P3_NICHE
from app.services.clinical_engine.profiles.base import BaseProfileSkeleton


class OrganicAcidsProfile(BaseProfileSkeleton):
    profile_key = "organic_acids_urine"
    document_type = "organic_acids_urine"
    priority = P3_NICHE

    def build_group_interpretation(self, values, findings):
        return [
            {"group": "Органические кислоты мочи", "markers": [], "interpretation": "Интерпретация через отдельный pipeline (organic_acids)."},
        ]
