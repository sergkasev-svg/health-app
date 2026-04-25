from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class FoodJournalEntry:
    food_items: list[str]
    symptoms: list[str]
    notes: str = ""


@dataclass
class FoodJournalAnalysisResult:
    repeated_foods: list[str]
    repeated_symptoms: list[str]
    likely_trigger_pairs: list[dict[str, Any]]
    summary_text: str


class FoodJournalAnalyzer:
    """
    Analyzes a lightweight food journal.
    Input example:
      [
        {"food_items": ["молоко", "мороженое"], "symptoms": ["вздутие", "понос"]},
        {"food_items": ["сыр", "вино"], "symptoms": ["головная боль", "покраснение"]}
      ]
    """

    def analyze(self, entries: list[dict[str, Any]]) -> FoodJournalAnalysisResult:
        food_counts: dict[str, int] = {}
        symptom_counts: dict[str, int] = {}
        pair_counts: dict[tuple[str, str], int] = {}

        for raw in entries:
            food_items = [str(x).strip().lower() for x in raw.get("food_items", []) if str(x).strip()]
            symptoms = [str(x).strip().lower() for x in raw.get("symptoms", []) if str(x).strip()]

            for food in food_items:
                food_counts[food] = food_counts.get(food, 0) + 1

            for symptom in symptoms:
                symptom_counts[symptom] = symptom_counts.get(symptom, 0) + 1

            for food in food_items:
                for symptom in symptoms:
                    key = (food, symptom)
                    pair_counts[key] = pair_counts.get(key, 0) + 1

        repeated_foods = sorted([food for food, count in food_counts.items() if count >= 2])
        repeated_symptoms = sorted([symptom for symptom, count in symptom_counts.items() if count >= 2])

        likely_trigger_pairs = [
            {
                "food": food,
                "symptom": symptom,
                "count": count,
            }
            for (food, symptom), count in sorted(pair_counts.items(), key=lambda x: x[1], reverse=True)
            if count >= 2
        ][:10]

        summary_parts: list[str] = []
        if repeated_foods:
            summary_parts.append("Повторяющиеся продукты: " + ", ".join(repeated_foods))
        if repeated_symptoms:
            summary_parts.append("Повторяющиеся симптомы: " + ", ".join(repeated_symptoms))
        if likely_trigger_pairs:
            pairs_text = "; ".join(
                f"{pair['food']} -> {pair['symptom']} ({pair['count']})"
                for pair in likely_trigger_pairs[:5]
            )
            summary_parts.append("Наиболее частые пары: " + pairs_text)

        summary_text = " | ".join(summary_parts) if summary_parts else "Повторяемых связей пока недостаточно."

        return FoodJournalAnalysisResult(
            repeated_foods=repeated_foods,
            repeated_symptoms=repeated_symptoms,
            likely_trigger_pairs=likely_trigger_pairs,
            summary_text=summary_text,
        )

