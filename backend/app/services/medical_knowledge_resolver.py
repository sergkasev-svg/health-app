"""
MedicalKnowledgeResolver: выбор подходящих источников для запроса
(клинические гайдлайны, питание, физ. активность). Использует существующие offline_search и knowledge.
Изолированный модуль.
"""
from typing import Any

from app.services.offline_search import search_offline_with_formats
from app.services.voice_medical_input import extract_symptoms_nutrition_activity_intent


def resolve_sources_for_query(user_message: str) -> dict[str, Any]:
    """
    Определяет тип запроса и возвращает контекст из подходящих источников:
    - clinical: офлайн-справочник (симптомы, первая помощь, лекарства)
    - nutrition: текст для нутрициологических рекомендаций (далее NutritionAnalysisEngine)
    - activity: текст для рекомендаций по активности (далее PhysicalActivityAnalysisEngine)
    """
    extracted = extract_symptoms_nutrition_activity_intent(user_message or "")
    intent = extracted.get("intent") or "general"
    formats = search_offline_with_formats(user_message or "", max_med=3, max_guide=5)
    professional = (formats.get("professional") or "").strip()
    simple = (formats.get("simple") or "").strip()

    return {
        "intent": intent,
        "clinical": professional,
        "clinical_simple": simple,
        "use_nutrition_engine": intent in ("nutrition", "general"),
        "use_activity_engine": intent in ("fitness", "general"),
    }
