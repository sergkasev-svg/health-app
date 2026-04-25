"""
Fallback: неизвестный/общий лабораторный документ.
"""
from __future__ import annotations

from app.services.clinical_engine.profile_registry import P3_NICHE
from app.services.clinical_engine.profiles.base import BaseProfileSkeleton


class GenericLabProfile(BaseProfileSkeleton):
    profile_key = "generic_lab"
    document_type = "generic_lab_document"
    priority = P3_NICHE

    def build_group_interpretation(self, values, findings):
        return [
            {"group": "Общие показатели", "markers": [], "interpretation": "Тип анализа не определён. Покажите документ врачу для интерпретации."},
        ]
