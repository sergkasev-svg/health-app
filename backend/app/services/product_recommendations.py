"""
Внутренние продуктовые рекомендации для запуска: какой tier пушить, где first paywall, сегмент, что не запускать рано.
"""
from __future__ import annotations

from typing import Any, Dict, List


def get_launch_recommendations() -> Dict[str, Any]:
    return {
        "preferred_first_tiers": ["free", "plus", "pro"],
        "first_tier_to_push": "plus",
        "reason": "Plus — основной массовый тариф; баланс цены и ценности (continuity, trends).",
        "first_paywall_placement": "after_first_report",
        "reason_first_paywall": "Показывать апгрейд после первой ценности (первый разбор), не до — выше доверие и конверсия.",
        "first_segment_to_launch": "b2c_general",
        "reason_segment": "B2C general — самый широкий спрос: разбор анализов, план действий, отчёт врачу.",
        "do_not_launch_too_early": [
            "family_as_mass_product",
            "clinic_as_scale_product",
            "aggressive_paywall_before_value",
        ],
        "reason_late": "Family — после отработки Plus/Pro. Clinic — пилот, не массовый запуск. Paywall до первой ценности — риск отторжения.",
        "strongest_conversion_signals": [
            "first_value_reached",
            "first_report_done",
            "upload_plus_symptoms",
        ],
        "wow_features_to_keep": [
            "physician_report",
            "continuity_summary",
            "trends",
        ],
        "recommendation_summary": "Запускать Free + Plus + Pro. Family — позже как expansion. Clinic — pilot motion. First paywall — после первого разбора. Сильнее всего конвертируют сигналы первой ценности и загрузки анализов.",
    }


def get_tier_launch_sequence() -> List[Dict[str, str]]:
    return [
        {"order": 1, "tier": "free", "note": "Вход и доверие"},
        {"order": 2, "tier": "plus", "note": "Основной платный"},
        {"order": 3, "tier": "pro", "note": "Power users, physician report"},
        {"order": 4, "tier": "family", "note": "Expansion после стабилизации Plus/Pro"},
        {"order": 5, "tier": "clinic", "note": "Pilot, не массовый запуск"},
    ]
