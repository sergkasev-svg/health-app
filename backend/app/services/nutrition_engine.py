from __future__ import annotations

from typing import Any


def analyze_nutrition(parsed, text: str) -> dict[str, Any]:
    """
    Простой контекстный слой по связи симптомов и питания.
    Не ставит диагноз, а только формирует паттерны и вопросы.
    """
    source_text = (text or "").lower()
    triggers = list(getattr(parsed, "triggers", []) or [])
    normalized_symptoms = list(getattr(parsed, "normalized_symptoms", []) or [])

    patterns: list[str] = []
    questions: list[str] = []
    possible_conditions: list[str] = []
    recommendations: list[str] = []

    if "fried_food" in triggers:
        patterns.append("fatty_food_trigger")
        questions.append("Ухудшение возникает после жирной или жареной пищи?")
        possible_conditions.extend(
            [
                "functional_dyspepsia",
                "biliary_reaction",
            ]
        )

    if "spicy_food" in triggers:
        patterns.append("spicy_food_trigger")
        questions.append("Становится ли хуже после острой пищи?")
        possible_conditions.extend(
            [
                "gastric_irritation",
                "reflux_related_symptoms",
            ]
        )

    if "dairy" in triggers:
        patterns.append("dairy_trigger")
        questions.append("Есть ли вздутие, урчание или послабление стула после молочных продуктов?")
        possible_conditions.extend(
            [
                "lactose_intolerance_pattern",
                "functional_bloating",
            ]
        )

    if "alcohol" in triggers:
        patterns.append("alcohol_trigger")
        questions.append("Связано ли ухудшение с алкоголем или на следующий день после него?")
        possible_conditions.extend(
            [
                "gastric_irritation",
                "biliary_reaction",
            ]
        )

    if "sunflower_seeds" in triggers:
        patterns.append("seed_trigger")
        questions.append("Бывает ли похожая реакция после семечек, орехов или другой жирной пищи?")
        possible_conditions.extend(
            [
                "functional_dyspepsia",
                "biliary_reaction",
            ]
        )

    if "stress" in triggers:
        patterns.append("stress_related_trigger")
        questions.append("Усиливаются ли симптомы на фоне стресса или тревоги?")
        possible_conditions.extend(
            [
                "functional_gastrointestinal_pattern",
                "stress_related_symptom_amplification",
            ]
        )

    if "abdominal_pain" in normalized_symptoms and "nausea" in normalized_symptoms:
        patterns.append("upper_gi_symptom_cluster")
        possible_conditions.extend(
            [
                "functional_dyspepsia",
                "gastritis_like_pattern",
            ]
        )

    if "diarrhea" in normalized_symptoms and ("dairy" in triggers or "fried_food" in triggers):
        patterns.append("post_food_loose_stool_pattern")
        possible_conditions.extend(
            [
                "food_intolerance_pattern",
                "functional_bowel_reaction",
            ]
        )

    if patterns:
        recommendations.extend(
            [
                "Вести простой пищевой дневник: продукт, время, симптомы, интенсивность.",
                "На 3–7 дней исключить явные провоцирующие продукты и оценить динамику.",
            ]
        )

    if "fried_food" in triggers or "sunflower_seeds" in triggers or "alcohol" in triggers:
        recommendations.append("До уточнения причины временно избегать жирной, жареной пищи и алкоголя.")

    if "dairy" in triggers:
        recommendations.append("Можно временно сократить молочные продукты до прояснения переносимости.")

    if "spicy_food" in triggers:
        recommendations.append("На время симптомов уменьшить острую и раздражающую пищу.")

    if not patterns and any(word in source_text for word in ["еда", "после еды", "после приема пищи", "после приёма пищи"]):
        questions.append("Есть ли связь симптомов с конкретными продуктами, объёмом еды или временем после еды?")

    # Убираем дубли, сохраняя порядок
    def _dedupe(values: list[str]) -> list[str]:
        seen = set()
        result = []
        for item in values:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    return {
        "patterns": _dedupe(patterns),
        "questions": _dedupe(questions),
        "possible_conditions": _dedupe(possible_conditions),
        "recommendations": _dedupe(recommendations),
    }