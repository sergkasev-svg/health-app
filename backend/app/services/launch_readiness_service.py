"""
Чеклист и сводка готовности к запуску.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.gtm_models import LaunchChecklistItem


def _build_checklist_items() -> List[LaunchChecklistItem]:
    return [
        LaunchChecklistItem(item_id="emergency_routing", area="product", title="Emergency routing validated", description="Проверена маршрутизация срочных случаев.", status="pending", priority="high"),
        LaunchChecklistItem(item_id="no_hallucination_leakage", area="safety", title="No hallucination leakage in user mode", description="В пользовательском режиме нет утечки галлюцинаций.", status="pending", priority="high"),
        LaunchChecklistItem(item_id="physician_report_gated", area="product", title="Physician report gated correctly", description="Отчёт для врача корректно закрыт на free.", status="pending", priority="high"),
        LaunchChecklistItem(item_id="onboarding_first_value", area="onboarding", title="Onboarding first value works", description="First value онбординга срабатывает.", status="pending", priority="high"),
        LaunchChecklistItem(item_id="upgrade_prompts_post_value", area="onboarding", title="Upgrade prompts are post-value", description="Апгрейд-подсказки показываются после первой ценности.", status="pending", priority="medium"),
        LaunchChecklistItem(item_id="health_endpoints", area="infra", title="Health endpoints working", description="Health /ready, /live отвечают.", status="pending", priority="high"),
        LaunchChecklistItem(item_id="quality_dashboard", area="infra", title="Quality dashboard accessible internally", description="Дашборд качества доступен внутренне.", status="pending", priority="medium"),
        LaunchChecklistItem(item_id="export_flow", area="product", title="Export flow tested", description="Экспорт отчётов протестирован.", status="pending", priority="medium"),
        LaunchChecklistItem(item_id="legal_disclaimer", area="legal_copy", title="Legal / disclaimer copy reviewed", description="Дисклеймер и правовые формулировки проверены.", status="pending", priority="high"),
        LaunchChecklistItem(item_id="billing_flow", area="billing", title="Billing flow (if enabled) tested", description="Платёжный поток протестирован при включении.", status="pending", priority="medium"),
        LaunchChecklistItem(item_id="support_faq", area="support", title="Support / FAQ copy ready", description="FAQ и поддержка готовы.", status="pending", priority="medium"),
        LaunchChecklistItem(item_id="b2b_materials", area="b2b", title="B2B materials (if pilot) ready", description="B2B материалы готовы при пилоте.", status="pending", priority="low"),
        LaunchChecklistItem(item_id="analytics_events", area="analytics", title="Key analytics events firing", description="Ключевые события аналитики отправляются.", status="pending", priority="medium"),
    ]


class LaunchReadinessService:
    def build_checklist(self) -> List[LaunchChecklistItem]:
        return _build_checklist_items()

    def build_readiness_summary(self) -> Dict[str, Any]:
        items = _build_checklist_items()
        by_area: Dict[str, List[Dict[str, Any]]] = {}
        for i in items:
            by_area.setdefault(i.area, []).append(i.model_dump())
        done = sum(1 for i in items if i.status == "done")
        total = len(items)
        high = [i for i in items if i.priority == "high"]
        return {
            "total_items": total,
            "done_count": done,
            "pending_count": total - done,
            "by_area": by_area,
            "high_priority": [i.model_dump() for i in high],
            "ready": done == total,
        }
