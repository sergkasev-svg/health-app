"""
Коагулограмма. P2.
ПТИ/INR, АЧТВ, фибриноген, Д-димер.
Скелет: в разработке.
"""
from __future__ import annotations

from app.services.clinical_engine.profile_registry import P2_CLINICALLY_STRONG
from app.services.clinical_engine.profiles.base import BaseProfileSkeleton


class CoagulationPanelProfile(BaseProfileSkeleton):
    profile_key = "coagulation_panel"
    document_type = "generic_lab_document"
    priority = P2_CLINICALLY_STRONG

    def build_group_interpretation(self, values, findings):
        return [
            {"group": "Коагуляция", "markers": ["inr", "pt", "aptt", "fibrinogen", "d_dimer"], "interpretation": "Профиль в разработке."},
        ]
