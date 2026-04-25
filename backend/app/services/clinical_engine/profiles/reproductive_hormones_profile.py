"""
Гормоны репродуктивной системы. P2.
ФСГ, ЛГ, эстрадиол, прогестерон, пролактин, тестостерон, SHBG, ДГЭА-S.
Скелет: в разработке.
"""
from __future__ import annotations

from app.services.clinical_engine.profile_registry import P2_CLINICALLY_STRONG
from app.services.clinical_engine.profiles.base import BaseProfileSkeleton


class ReproductiveHormonesProfile(BaseProfileSkeleton):
    profile_key = "reproductive_hormones_panel"
    document_type = "generic_lab_document"
    priority = P2_CLINICALLY_STRONG

    def build_group_interpretation(self, values, findings):
        return [
            {"group": "Репродуктивные гормоны", "markers": ["fsh", "lh", "estradiol", "progesterone", "prolactin", "testosterone", "shbg", "dhea_s"], "interpretation": "Профиль в разработке."},
        ]
