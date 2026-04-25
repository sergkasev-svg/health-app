"""
Профиль углеводного обмена. P0.
Глюкоза натощак, HbA1c, фруктозамин, инсулин, HOMA-IR.
Скелет: правила частично в lipid_panel (glucose_rules); полный профиль — в разработке.
"""
from __future__ import annotations

from app.services.clinical_engine.profile_registry import P0_MUST_HAVE
from app.services.clinical_engine.profiles.base import BaseProfileSkeleton


class GlucoseMetabolismProfile(BaseProfileSkeleton):
    profile_key = "glucose_metabolism"
    document_type = "biochemistry_blood"
    priority = P0_MUST_HAVE

    def build_group_interpretation(self, values, findings):
        return [
            {"group": "Углеводный обмен", "markers": ["glucose", "hba1c", "fructosamine"], "interpretation": "Профиль в разработке. Используется в рамках биохимии (HbA1c, фруктозамин)."},
        ]
