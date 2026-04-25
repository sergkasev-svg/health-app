"""
Профиль аутоиммунных маркеров (ANA, ENA, RF, anti-CCP и т.д.). P3.
Скелет: высокий риск неверной самодиагностики — только осторожные заглушки.
"""
from __future__ import annotations

from app.services.clinical_engine.profile_registry import P3_NICHE
from app.services.clinical_engine.profiles.base import BaseProfileSkeleton


class AutoimmunePanelProfile(BaseProfileSkeleton):
    profile_key = "autoimmune_panel"
    document_type = "generic_lab_document"
    priority = P3_NICHE

    def build_group_interpretation(self, values, findings):
        return [
            {
                "group": "Аутоиммунные маркеры",
                "markers": ["ana", "ena", "rf", "anti_ccp"],
                "interpretation": "Профиль в разработке. Результаты требуют очной интерпретации ревматологом/врачом.",
            },
        ]
