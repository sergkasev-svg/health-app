"""
Публичная точка входа для осевого Clinical Routing органических кислот (OA).

Реализация: ``clinical_routing_engine.build_clinical_routing_output`` (в том же модуле —
также ``ClinicalRoutingEngine`` для маршрутизации диалога / панелей).

Импортируйте отсюда: ``from app.services.clinical_oa_axis_routing import build_clinical_routing_output``.
"""
from __future__ import annotations

from app.services.clinical_routing_engine import build_clinical_routing_output

__all__ = ("build_clinical_routing_output",)
