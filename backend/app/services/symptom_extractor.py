from __future__ import annotations

from dataclasses import dataclass

from app.services.text_matchers import match_any


@dataclass
class SymptomExtractionResult:
    normalized_text: str
    matched_symptoms: list[str]
    zone_scores: dict[str, int]
    detected_zone: str
    cluster_scores: dict[str, int]
    detected_cluster: str


class SymptomExtractor:
    """
    Extracts symptoms, detects zone and cluster using routing rules.
    """

    def __init__(self, routing_config: dict) -> None:
        self.routing_config = routing_config

    def extract(
        self,
        normalized_text: str,
        trigger_groups: list[str],
        recurrent: bool,
    ) -> SymptomExtractionResult:
        matched_symptoms = self._extract_symptoms(normalized_text)
        zone_scores = self._score_zones(normalized_text)
        detected_zone = self._pick_best_zone(zone_scores)
        cluster_scores = self._score_clusters(
            normalized_text=normalized_text,
            detected_zone=detected_zone,
            trigger_groups=trigger_groups,
            recurrent=recurrent,
        )
        detected_cluster = self._pick_best_cluster(cluster_scores, detected_zone)

        return SymptomExtractionResult(
            normalized_text=normalized_text,
            matched_symptoms=matched_symptoms,
            zone_scores=zone_scores,
            detected_zone=detected_zone,
            cluster_scores=cluster_scores,
            detected_cluster=detected_cluster,
        )

    def _extract_symptoms(self, normalized_text: str) -> list[str]:
        phrases: list[str] = []
        for rule in self.routing_config.get("zone_rules", []):
            phrases.extend(rule.get("if_any_symptoms", []))
        return match_any(normalized_text, phrases, allow_fuzzy=True, threshold=0.88)

    def _score_zones(self, normalized_text: str) -> dict[str, int]:
        scores: dict[str, int] = {}
        for rule in self.routing_config.get("zone_rules", []):
            zone = str(rule.get("zone", "upper_gi_zone"))
            symptoms = rule.get("if_any_symptoms", [])
            matched = match_any(normalized_text, symptoms, allow_fuzzy=True, threshold=0.88)
            score = sum(self._weight_for_symptom(symptom) for symptom in matched)
            scores[zone] = score
        return scores

    def _score_clusters(
        self,
        *,
        normalized_text: str,
        detected_zone: str,
        trigger_groups: list[str],
        recurrent: bool,
    ) -> dict[str, int]:
        scores: dict[str, int] = {}

        for rule in self.routing_config.get("cluster_rules", []):
            cluster = str(rule.get("cluster", ""))
            required_zone = rule.get("requires_zone")
            if required_zone and required_zone != detected_zone:
                continue

            score = 0

            required_trigger_group = rule.get("requires_trigger_group")
            if required_trigger_group:
                if required_trigger_group not in trigger_groups:
                    continue
                score += 6

            required_any_symptoms = rule.get("requires_any_symptoms", [])
            if required_any_symptoms:
                matched = match_any(normalized_text, required_any_symptoms, allow_fuzzy=True, threshold=0.88)
                if not matched:
                    continue
                score += sum(self._weight_for_symptom(symptom) for symptom in matched)

            context_flags = rule.get("requires_context_flags", [])
            if "recurrent_pattern" in context_flags:
                if not recurrent:
                    continue
                score += 4

            scores[cluster] = score

        return scores

    @staticmethod
    def _pick_best_zone(scores: dict[str, int]) -> str:
        if not scores:
            return "upper_gi_zone"
        return max(scores.items(), key=lambda x: x[1])[0]

    def _pick_best_cluster(self, scores: dict[str, int], detected_zone: str) -> str:
        if not scores:
            return self._default_cluster_for_zone(detected_zone)
        return max(scores.items(), key=lambda x: x[1])[0]

    @staticmethod
    def _default_cluster_for_zone(zone: str) -> str:
        defaults = {
            "right_upper_abdominal_zone": "right_upper_abdominal_discomfort_after_fatty_food",
            "upper_gi_zone": "upper_abdominal_heaviness_after_food",
            "bowel_zone": "bloating_gas_after_onion_garlic_beans_fruit_juice_honey",
            "systemic_zone": "sleepiness_weakness_after_heavy_meal",
        }
        return defaults.get(zone, "upper_abdominal_heaviness_after_food")

    @staticmethod
    def _weight_for_symptom(symptom: str) -> int:
        symptom = symptom.lower()
        heavy = {
            "боль справа под ребрами": 5,
            "боль справа под рёбрами": 5,
            "кислая отрыжка": 5,
            "хуже лежа": 5,
            "хуже лёжа": 5,
            "диарея": 5,
            "рвота": 5,
            "температура": 5,
            "изжога": 5,
            "жжение": 5,
            "вздутие": 4,
            "урчание": 4,
            "газы": 4,
            "слабость": 4,
            "головокружение": 4,
            "головная боль": 4,
            "горечь во рту": 4,
            "тяжесть": 3,
            "тошнота": 3,
            "отрыжка": 3,
            "сонливость": 3,
        }
        return heavy.get(symptom, 1)

"""
SymptomExtractor: structured extraction from free-text symptom descriptions.
Isolated helper for voice/chat pipelines.
"""
import re
from typing import Any

from app.services.voice_medical_input import extract_symptoms_nutrition_activity_intent


_PAIN_LOCATIONS = (
    "голова",
    "горло",
    "грудь",
    "живот",
    "спина",
    "сустав",
    "ухо",
    "нос",
    "поясница",
)


def extract_symptom_payload(text: str) -> dict[str, Any]:
    """
    Returns structured symptom payload:
    - complaints: list[str]
    - temperature_c: float | None
    - pain_locations: list[str]
    - duration_hint: str
    - severity_hint: str
    - intent: illness/nutrition/fitness/general
    """
    text = (text or "").strip()
    basic = extract_symptoms_nutrition_activity_intent(text)
    lower = text.lower()

    temp = None
    m = re.search(r"(\d{2}(?:[.,]\d)?)\s*°?\s*c?", lower)
    if m:
        try:
            temp = float(m.group(1).replace(",", "."))
        except Exception:
            temp = None

    pain_locations = [loc for loc in _PAIN_LOCATIONS if loc in lower]

    duration_hint = ""
    for key in ("день", "дня", "недел", "месяц", "час", "сут"):
        if key in lower:
            duration_hint = "duration_provided"
            break
    if not duration_hint:
        duration_hint = "duration_unknown"

    severity_hint = "moderate"
    if any(k in lower for k in ("очень", "сильно", "невыносим", "39", "40")):
        severity_hint = "high"
    if any(k in lower for k in ("слегка", "немного", "легко")):
        severity_hint = "low"

    return {
        "complaints": (basic.get("symptoms") or [])[:10],
        "temperature_c": temp,
        "pain_locations": pain_locations,
        "duration_hint": duration_hint,
        "severity_hint": severity_hint,
        "intent": basic.get("intent") or "general",
    }

