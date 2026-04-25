"""
Обогащение ответа по отчёту органических кислот: паттерн → смысл → что делать → что проверить
+ опционально блок микробиома по контексту консультации.
Не назначения — практические next steps для обсуждения с врачом.
"""
from __future__ import annotations

from typing import Any, Dict, List


def derive_markers_from_organic_acids_report(
    report: Dict[str, Any],
) -> Dict[str, bool]:
    """
    Строит маркеры для clinical_action_engine из physician report.
    Алиас для совместимости с report_enricher_example: тот ожидал parsed_values
    с ключами meta_methylhippuric_high и т.д.; здесь мы берём данные из report.
    """
    from app.services.clinical_action_engine import derive_markers_from_physician_report

    return derive_markers_from_physician_report(report)


def enrich_organic_acids_response(
    report: Dict[str, Any],
    consultation_payload: Dict[str, Any] | None = None,
    base_response_parts: List[str] | None = None,
) -> str:
    """
    Обогащает текст ответа: блок по clinical_action_engine (паттерн, смысл, действия, что проверить)
    и при наличии consultation_payload — краткий блок по осям микробиома.
    Итог пропускается через sanitize_microbiome_text.
    """
    from app.services.clinical_action_engine import (
        derive_markers_from_physician_report,
        render_patient_facing_plan,
    )
    from app.services.microbiome_guardrails import sanitize_microbiome_text

    markers = derive_markers_from_physician_report(report)
    doc_summary = report.get("document_summary") or {}
    try:
        age_years = int(doc_summary.get("age_years") or 0)
    except (TypeError, ValueError):
        age_years = 0

    plan_text = render_patient_facing_plan(markers, age_years=age_years)
    parts = list(base_response_parts or [])
    parts.append("")
    parts.append(plan_text)

    if consultation_payload:
        from app.services.microbiome_axes_engine import calc_microbiome_axes

        axes = calc_microbiome_axes(consultation_payload)
        if axes:
            parts.append("")
            parts.append("Дополнительный модуль: микробиом")
            level_ru = {
                "low": "низкий",
                "moderate": "умеренный",
                "high": "высокий",
            }
            for axis in axes:
                level_label = level_ru.get(axis.level, axis.level)
                parts.append(f"- {axis.axis}: {level_label}")
                for insight in axis.insights[:2]:
                    parts.append(f"  • {insight}")
                for rec in axis.recommendations[:2]:
                    parts.append(f"  • Рекомендация: {rec}")

    return sanitize_microbiome_text("\n".join(parts))
