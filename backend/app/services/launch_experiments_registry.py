"""
Реестр экспериментов запуска: гипотезы, метрики, заметки по rollout.
"""
from __future__ import annotations

from typing import Any, Dict, List
from pydantic import BaseModel, Field


class LaunchExperiment(BaseModel):
    experiment_id: str = ""
    hypothesis: str = ""
    primary_metric: str = ""
    secondary_metric: str = ""
    rollout_notes: str = ""


def get_launch_experiments() -> List[LaunchExperiment]:
    return [
        LaunchExperiment(
            experiment_id="paywall_after_first_report_vs_locked",
            hypothesis="Paywall после первого отчёта даёт лучшую конверсию, чем paywall при попытке открыть заблокированную фичу.",
            primary_metric="conversion_to_plus_pro",
            secondary_metric="bounce_after_paywall",
            rollout_notes="A: после первого отчёта; B: при клике на physician report.",
        ),
        LaunchExperiment(
            experiment_id="physician_report_teaser_wording_ab",
            hypothesis="Формулировка A («Подробный отчёт для врача в Pro») vs B («Покажите врачу структурированный отчёт — в Pro») влияет на конверсию в Pro.",
            primary_metric="pro_conversion",
            secondary_metric="cta_click",
            rollout_notes="A/B по тексту teaser.",
        ),
        LaunchExperiment(
            experiment_id="upload_first_vs_symptom_first_onboarding",
            hypothesis="Онбординг «сначала загрузите анализы» vs «сначала опишите симптомы» влияет на first value и retention.",
            primary_metric="first_value_reached_rate",
            secondary_metric="day1_retention",
            rollout_notes="Upload-first vs symptom-first flow.",
        ),
        LaunchExperiment(
            experiment_id="plus_vs_pro_card_emphasis",
            hypothesis="Акцент на карточке Plus (рекомендованный) vs равный акцент Plus/Pro влияет на распределение конверсий.",
            primary_metric="plus_conversion",
            secondary_metric="pro_conversion",
            rollout_notes="Pricing page: recommended badge and order.",
        ),
        LaunchExperiment(
            experiment_id="return_user_followup_prompt_wording",
            hypothesis="Разные формулировки приглашения вернуться («Есть новые данные» vs «Обновите разбор») влияют на return rate.",
            primary_metric="return_rate",
            secondary_metric="followup_upload_rate",
            rollout_notes="Copy for return-user prompt.",
        ),
        LaunchExperiment(
            experiment_id="free_upload_cap_messaging",
            hypothesis="Явное сообщение лимита загрузок на free («3 разбора в месяц») vs мягкое («больше в Plus») влияет на upgrade и восприятие.",
            primary_metric="upgrade_after_limit",
            secondary_metric="support_tickets",
            rollout_notes="Limit messaging on free tier.",
        ),
    ]


def get_experiments_as_dict() -> List[Dict[str, Any]]:
    return [e.model_dump() for e in get_launch_experiments()]
