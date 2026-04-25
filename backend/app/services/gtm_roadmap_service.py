"""
Roadmap 30 / 60 / 90 дней: product, growth, content, b2b, ops, analytics.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.gtm_models import GTMRoadmapItem


def _roadmap_items() -> List[GTMRoadmapItem]:
    return [
        GTMRoadmapItem(phase="30d", stream="product", title="Stabilize onboarding", description="Стабилизировать онбординг и первый контакт.", owner_hint=None, priority="high"),
        GTMRoadmapItem(phase="30d", stream="growth", title="Validate first value funnel", description="Проверить воронку первой ценности.", owner_hint=None, priority="high"),
        GTMRoadmapItem(phase="30d", stream="product", title="Validate lab upload flow", description="Проверить загрузку и разбор анализов.", owner_hint=None, priority="high"),
        GTMRoadmapItem(phase="30d", stream="analytics", title="Measure first conversion", description="Измерить первую конверсию в апгрейд.", owner_hint=None, priority="high"),
        GTMRoadmapItem(phase="30d", stream="content", title="Refine physician report teaser", description="Уточнить формулировки teaser отчёта для врача.", owner_hint=None, priority="medium"),
        GTMRoadmapItem(phase="30d", stream="ops", title="Collect early failure cases", description="Собирать ранние кейсы провалов для качества.", owner_hint=None, priority="medium"),
        GTMRoadmapItem(phase="60d", stream="growth", title="Optimize paywall placements", description="Оптимизировать места показа paywall.", owner_hint=None, priority="high"),
        GTMRoadmapItem(phase="60d", stream="product", title="Test plus/pro packaging", description="Тестировать упаковку Plus и Pro.", owner_hint=None, priority="high"),
        GTMRoadmapItem(phase="60d", stream="growth", title="Improve retention and follow-up return", description="Улучшить возврат и follow-up.", owner_hint=None, priority="high"),
        GTMRoadmapItem(phase="60d", stream="product", title="Start family beta", description="Запустить бета тарифа Семья.", owner_hint=None, priority="medium"),
        GTMRoadmapItem(phase="60d", stream="b2b", title="Begin B2B discovery with clinics/labs", description="Начать B2B discovery с клиниками/лабами.", owner_hint=None, priority="medium"),
        GTMRoadmapItem(phase="90d", stream="product", title="Launch family tier if ready", description="Запустить тариф Семья при готовности.", owner_hint=None, priority="high"),
        GTMRoadmapItem(phase="90d", stream="b2b", title="Pilot clinic mode", description="Пилот режима для клиник.", owner_hint=None, priority="high"),
        GTMRoadmapItem(phase="90d", stream="product", title="Launch branded physician reports", description="Запустить брендированные отчёты для врача.", owner_hint=None, priority="medium"),
        GTMRoadmapItem(phase="90d", stream="analytics", title="Measure cohort retention / paid retention", description="Измерить удержание когорт и платящих.", owner_hint=None, priority="high"),
        GTMRoadmapItem(phase="90d", stream="b2b", title="Build outbound B2B materials", description="Подготовить исходящие B2B материалы.", owner_hint=None, priority="medium"),
    ]


class GTMRoadmapService:
    def build_roadmap(self) -> Dict[str, Any]:
        items = _roadmap_items()
        by_phase: Dict[str, List[Dict[str, Any]]] = {"30d": [], "60d": [], "90d": []}
        by_stream: Dict[str, List[Dict[str, Any]]] = {}
        for i in items:
            by_phase.setdefault(i.phase, []).append(i.model_dump())
            by_stream.setdefault(i.stream, []).append(i.model_dump())
        return {
            "phases": ["30d", "60d", "90d"],
            "streams": list(by_stream.keys()),
            "by_phase": by_phase,
            "by_stream": by_stream,
            "items": [i.model_dump() for i in items],
        }
