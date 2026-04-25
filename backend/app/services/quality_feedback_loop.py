"""
Обратная связь по качеству: сбор провалов, кластеризация, рекомендации по правилам и промптам.
Только suggestions/report, без авто-изменения продакшена.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.quality_store import QualityStore


def collect_recent_failures(store: QualityStore, limit: int = 200) -> List[Dict[str, Any]]:
    return store.get_failures(limit=limit)


def cluster_similar_failures(failures: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    by_category: Dict[str, List[Dict[str, Any]]] = {}
    for f in failures:
        cat = f.get("category") or "other"
        by_category.setdefault(cat, []).append(f)
    return by_category


def suggest_rule_improvements(failures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    clusters = cluster_similar_failures(failures)
    suggestions = []
    if clusters.get("hallucination"):
        suggestions.append({
            "area": "diagnosis_filter",
            "message": "Усилить фильтр редких диагнозов (малярия, сепсис, импетиго) в diagnosis_filter / physician report generator.",
            "count": len(clusters["hallucination"]),
        })
    if clusters.get("bad_triage"):
        suggestions.append({
            "area": "decision_engine",
            "message": "Проверить логику триажа: при red_flags state должен быть emergency или doctor_soon.",
            "count": len(clusters["bad_triage"]),
        })
    if clusters.get("parsing_failure"):
        suggestions.append({
            "area": "document_extraction",
            "message": "Улучшить парсинг загружаемых файлов; добавить fallback для неизвестных типов.",
            "count": len(clusters["parsing_failure"]),
        })
    if clusters.get("duplicate_questions"):
        suggestions.append({
            "area": "followup_engine",
            "message": "Жёстче фильтровать уже отвеченные вопросы в get_next_questions.",
            "count": len(clusters["duplicate_questions"]),
        })
    if clusters.get("gating_issue"):
        suggestions.append({
            "area": "product_gating_policy",
            "message": "Убедиться, что при emergency/red_flags physician_report не гейтится.",
            "count": len(clusters["gating_issue"]),
        })
    return suggestions


def suggest_prompt_improvements(failures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    suggestions = []
    clusters = cluster_similar_failures(failures)
    if clusters.get("weak_answer"):
        suggestions.append({
            "area": "build_final_user_message",
            "message": "Усилить минимальную длину и полезность final_user_message при наличии ввода.",
        })
    if clusters.get("hallucination"):
        suggestions.append({
            "area": "physician_report_generator",
            "message": "Явно перечислять NOISE_HYPOTHESES и фильтровать в assessment.",
        })
    return suggestions
