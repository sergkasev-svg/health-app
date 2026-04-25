from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.food_response_builder import (
    build_doctor_safe_output,
    build_patient_safe_response,
    build_urgent_response,
)
from app.services.medical_guardrails import MedicalGuardrails
from app.services.reasoning_debug import make_reasoning_debug_payload
from app.services.text_matchers import contains_phrase, match_any, normalize_text


@dataclass
class FoodRoutingContext:
    recurrent: bool = False
    debug: bool = False
    doctor_safe: bool = False
    extra_flags: dict[str, Any] = field(default_factory=dict)


class FoodSymptomRouterV3:
    """
    Production-beta router with:
    - fuzzy matching
    - cause scoring
    - patient-safe output
    - doctor-safe JSON output
    """

    def __init__(self, configs: dict[str, Any]) -> None:
        self.super_master = configs["super_master"]
        self.templates = configs["templates"]
        self.routing = configs["routing"]

        self.causes_map: dict[str, dict[str, Any]] = {
            cause["id"]: cause
            for cause in self.super_master.get("causes", [])
            if isinstance(cause, dict) and "id" in cause
        }
        self.guardrails = MedicalGuardrails(self.routing)

    def route(self, user_input: str, context: FoodRoutingContext | None = None) -> dict[str, Any]:
        context = context or FoodRoutingContext()
        normalized = normalize_text(user_input)

        guard = self.guardrails.check(normalized)
        if guard.is_urgent:
            urgent_response = build_urgent_response(
                matched_red_flags=guard.matched_red_flags,
                urgent_reason=guard.urgent_reason,
            )
            doctor_json = build_doctor_safe_output(
                normalized=normalized,
                zone="urgent_route",
                cluster="urgent_route",
                trigger_groups=[],
                matched_red_flags=guard.matched_red_flags,
                cause_scores={"urgent_general_route": 100},
                ranked_cause_ids=["urgent_general_route"],
                recommended_tests=[],
                recurrent=context.recurrent,
            )
            if context.debug:
                urgent_response["debug"] = make_reasoning_debug_payload(
                    normalized=normalized,
                    zone="urgent_route",
                    cluster="urgent_route",
                    trigger_groups=[],
                    matched_red_flags=guard.matched_red_flags,
                    cause_scores={"urgent_general_route": 100},
                    ranked_causes=["urgent_general_route"],
                    recurrent=context.recurrent,
                    template="urgent_only",
                    recommended_tests=[],
                )
            if context.doctor_safe:
                urgent_response["doctor_safe"] = doctor_json
            return urgent_response

        trigger_groups = self.detect_trigger_groups(normalized)
        zone = self.detect_zone(normalized)
        cluster = self.detect_cluster(normalized, zone, trigger_groups, context)
        cause_scores = self.score_causes(
            normalized=normalized,
            zone=zone,
            cluster=cluster,
            trigger_groups=trigger_groups,
            recurrent=context.recurrent,
        )
        ranked_causes = self.rank_from_scores(cause_scores)
        template_name = self.select_template(cluster)
        recommended_tests = self.select_tests(ranked_causes, recurrent=context.recurrent)

        response = build_patient_safe_response(
            template_name=template_name,
            templates=self.templates,
            ranked_cause_ids=ranked_causes,
            causes_map=self.causes_map,
            recommended_tests=recommended_tests,
            recurrent=context.recurrent,
        )

        if context.debug:
            response["debug"] = make_reasoning_debug_payload(
                normalized=normalized,
                zone=zone,
                cluster=cluster,
                trigger_groups=trigger_groups,
                matched_red_flags=[],
                cause_scores=cause_scores,
                ranked_causes=ranked_causes,
                recurrent=context.recurrent,
                template=template_name,
                recommended_tests=recommended_tests,
            )

        if context.doctor_safe:
            response["doctor_safe"] = build_doctor_safe_output(
                normalized=normalized,
                zone=zone,
                cluster=cluster,
                trigger_groups=trigger_groups,
                matched_red_flags=[],
                cause_scores=cause_scores,
                ranked_cause_ids=ranked_causes,
                recommended_tests=recommended_tests,
                recurrent=context.recurrent,
            )

        return response

    def detect_trigger_groups(self, normalized: str) -> list[str]:
        trigger_synonyms = self.routing.get("normalization", {}).get("trigger_synonyms", {})

        matched_groups: list[str] = []
        for group_name, values in trigger_synonyms.items():
            matched = match_any(normalized, values, allow_fuzzy=True, threshold=0.86)
            if matched:
                matched_groups.append(group_name)

        return matched_groups

    def detect_zone(self, normalized: str) -> str:
        zone_rules = self.routing.get("zone_rules", [])
        best_zone = "upper_gi_zone"
        best_score = -1

        for rule in zone_rules:
            zone = str(rule.get("zone", "upper_gi_zone"))
            symptoms = rule.get("if_any_symptoms", [])
            matched = match_any(normalized, symptoms, allow_fuzzy=True, threshold=0.88)
            score = sum(self._weight_for_symptom(symptom) for symptom in matched)

            if score > best_score:
                best_score = score
                best_zone = zone

        return best_zone

    def detect_cluster(
        self,
        normalized: str,
        zone: str,
        trigger_groups: list[str],
        context: FoodRoutingContext,
    ) -> str:
        cluster_rules = self.routing.get("cluster_rules", [])
        best_cluster = self._default_cluster_for_zone(zone)
        best_score = -1

        for rule in cluster_rules:
            cluster = str(rule.get("cluster", ""))
            required_zone = rule.get("requires_zone")
            if required_zone and required_zone != zone:
                continue

            score = 0

            required_trigger_group = rule.get("requires_trigger_group")
            if required_trigger_group:
                if required_trigger_group not in trigger_groups:
                    continue
                score += 6

            required_any_symptoms = rule.get("requires_any_symptoms", [])
            matched = match_any(normalized, required_any_symptoms, allow_fuzzy=True, threshold=0.88)
            if required_any_symptoms and not matched:
                continue
            score += sum(self._weight_for_symptom(symptom) for symptom in matched)

            context_flags = rule.get("requires_context_flags", [])
            if "recurrent_pattern" in context_flags:
                if not context.recurrent:
                    continue
                score += 4

            if score > best_score:
                best_score = score
                best_cluster = cluster

        return best_cluster

    def score_causes(
        self,
        *,
        normalized: str,
        zone: str,
        cluster: str,
        trigger_groups: list[str],
        recurrent: bool,
    ) -> dict[str, int]:
        cause_scores: dict[str, int] = {}

        # Base from cluster
        cluster_data = self.super_master.get("symptom_clusters", {}).get(cluster, {})
        cluster_ranked = list(cluster_data.get("ranked_causes", []))
        if not cluster_ranked:
            cluster_ranked = self._fallback_causes_for_zone(zone)

        for idx, cause_id in enumerate(cluster_ranked):
            cause_scores[cause_id] = cause_scores.get(cause_id, 0) + max(12 - idx * 2, 2)

        # Apply cause metadata
        for cause_id in list(cause_scores.keys()):
            cause = self.causes_map.get(cause_id, {})
            title = str(cause.get("title", "")).lower()
            typical_symptoms = cause.get("typical_symptoms", [])
            when_to_raise = cause.get("when_to_raise", [])

            matched_symptoms = match_any(normalized, typical_symptoms, allow_fuzzy=True, threshold=0.86)
            cause_scores[cause_id] += len(matched_symptoms) * 2

            matched_raise = match_any(normalized, when_to_raise, allow_fuzzy=True, threshold=0.86)
            cause_scores[cause_id] += len(matched_raise) * 2

            # Trigger compatibility
            if "молоч" in title and "dairy" in trigger_groups:
                cause_scores[cause_id] += 5
            if "гистамин" in title and "histamine_like" in trigger_groups:
                cause_scores[cause_id] += 6
            if "глюкоз" in title and "sweet_load" in trigger_groups:
                cause_scores[cause_id] += 6
            if "желч" in title and "fatty_fried" in trigger_groups:
                cause_scores[cause_id] += 5
            if "рефлюкс" in title and self._has_any(
                normalized, ["изжога", "жжение", "кислая отрыжка", "хуже лежа", "хуже лёжа"]
            ):
                cause_scores[cause_id] += 6
            if "диспепс" in title and self._has_any(normalized, ["тяжесть", "переполненность", "тошнота", "отрыжка"]):
                cause_scores[cause_id] += 5

        # Ranking overrides
        for override in self.routing.get("cause_ranking_overrides", []):
            if self._override_matches(override, normalized, trigger_groups):
                for cause_id in override.get("promote", []):
                    cause_scores[cause_id] = cause_scores.get(cause_id, 0) + 8

        # Guardrails against overcalling
        if not recurrent:
            cause_scores.pop("ibs_pattern_if_recurrent", None)

        if "histamine_like" not in trigger_groups:
            cause_scores.pop("histamine_conditional_pattern", None)

        if not self._has_any(normalized, ["боль в спину", "многократная рвота", "температура", "сильная боль"]):
            cause_scores.pop("pancreatic_warning_if_severe", None)

        return dict(sorted(cause_scores.items(), key=lambda x: x[1], reverse=True))

    @staticmethod
    def rank_from_scores(cause_scores: dict[str, int]) -> list[str]:
        return [cause_id for cause_id, _ in sorted(cause_scores.items(), key=lambda x: x[1], reverse=True)][:5]

    def select_template(self, cluster: str) -> str:
        for rule in self.routing.get("template_selection_rules", []):
            if rule.get("if_cluster") == cluster:
                return str(rule.get("template"))
        return "base_response"

    def select_tests(self, ranked_causes: list[str], recurrent: bool) -> list[str]:
        if not recurrent:
            return []

        recommendations: list[str] = []
        for rule in self.routing.get("tests_rules", []):
            if not rule.get("if_recurrent", False):
                continue

            allowed_causes = set(rule.get("if_any_causes", []))
            if allowed_causes and allowed_causes.intersection(ranked_causes):
                recommendations.extend(rule.get("recommend", []))

        return list(dict.fromkeys(recommendations))

    @staticmethod
    def _override_matches(
        override: dict[str, Any],
        normalized: str,
        trigger_groups: list[str],
    ) -> bool:
        trigger_group = override.get("if_trigger_group")
        if trigger_group and trigger_group not in trigger_groups:
            return False

        required_symptoms = override.get("if_any_symptoms", [])
        if required_symptoms and not match_any(normalized, required_symptoms, allow_fuzzy=True, threshold=0.88):
            return False

        return True

    @staticmethod
    def _weight_for_symptom(symptom: str) -> int:
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
            "тяжесть": 3,
            "тошнота": 3,
            "отрыжка": 3,
            "сонливость": 3,
            "горечь": 4,
        }
        return heavy.get(symptom.lower(), 1)

    @staticmethod
    def _has_any(normalized: str, phrases: list[str]) -> bool:
        return any(contains_phrase(normalized, phrase) for phrase in phrases)

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
    def _fallback_causes_for_zone(zone: str) -> list[str]:
        mapping = {
            "right_upper_abdominal_zone": [
                "biliary_pattern",
                "fatty_food_overload",
                "pancreatic_warning_if_severe",
            ],
            "upper_gi_zone": [
                "functional_dyspepsia",
                "fatty_food_overload",
                "reflux_pattern",
                "simple_overeating",
            ],
            "bowel_zone": [
                "dairy_lactose_pattern",
                "fodmap_fermentation_pattern",
                "simple_overeating_or_fast_eating",
            ],
            "systemic_zone": [
                "postprandial_vascular_pattern",
                "fatty_food_systemic_overload",
                "sugar_glucose_pattern",
                "dehydration_pattern",
            ],
        }
        return mapping.get(zone, ["functional_dyspepsia", "simple_overeating"])

