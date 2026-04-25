"""
Профиль онкомаркеров. P3.

ВАЖНО: не использовать для скрининга и самодиагностики без врача.
Только заглушка и дисклеймер до появления жёстких клинических правил.
"""
from __future__ import annotations

from app.services.clinical_engine.profile_registry import P3_NICHE
from app.services.clinical_engine.profiles.base import BaseProfileSkeleton


class OncologyMarkersPanelProfile(BaseProfileSkeleton):
    profile_key = "oncology_markers_panel"
    document_type = "generic_lab_document"
    priority = P3_NICHE

    def build_hypotheses(self, values, findings):
        return [
            "Онкомаркеры не устанавливают диагноз без клиники и визуализации; интерпретация только врачом-онкологом.",
        ]

    def build_group_interpretation(self, values, findings):
        return [
            {
                "group": "Онкомаркеры",
                "markers": [],
                "interpretation": "Профиль в разработке. Результаты не являются скринингом и не заменяют очный осмотр.",
            },
        ]
