from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.food_response_builder import build_patient_safe_response, build_urgent_response
from app.services.medical_guardrails import MedicalGuardrails
from app.services.reasoning_debug import make_reasoning_debug_payload


@dataclass
class FoodRoutingContext:
    recurrent: bool = False
    debug: bool = False
    extra_flags: dict[str, Any] = field(default_factory=dict)


class FoodSymptomRouter:
    """
    Main router for post-meal complaints.

    Features:
    - red flags via separate guardrails
    - weighted zone detection
    - weighted cluster detection
    - cause ranking with overrides
    - recurrent-aware logic
    - debug payload
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
        normalized = self.normalize_input(user_input)

        guard = self.guardrails.check(normalized)
        if guard.is_urgent:
            response = build_urgent_response(
                matched_red_flags=guard.matched_red_flags,
                urgent_reason=guard.urgent_reason,
            )
            if context.debug:
                response["debug"] = make_reasoning_debug_payload(
                    normalized=normalized,
                    zone="urgent_route",
                    cluster="urgent_route",
                    trigger_groups=[],
                    matched_red_flags=guard.matched_red_flags,
                    ranked_causes=["urgent_general_route"],
                    recurrent=context.recurrent,
                    template="urgent_only",
                    recommended_tests=[],
                )
            return response

        trigger_groups = self.detect_trigger_groups(normalized)
        zone = self.detect_zone(normalized)
        cluster = self.detect_cluster(normalized, zone, trigger_groups, context)
        ranked_causes = self.rank_causes(
            normalized=normalized,
            zone=zone,
            cluster=cluster,
            trigger_groups=trigger_groups,
            recurrent=context.recurrent,
        )
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
                ranked_causes=ranked_causes,
                recurrent=context.recurrent,
                template=template_name,
                recommended_tests=recommended_tests,
            )

        return response

    @staticmethod
    def normalize_input(user_input: str) -> str:
        text = user_input.lower().strip()
        text = text.replace("ё", "е")
        text = re.sub(r"\s+", " ", text)
        return text

    def detect_red_flags(self, normalized: str) -> list[str]:
        red_flag_rules = self.routing.get("red_flag_rules", {})
        match_any = red_flag_rules.get("match_any", [])

        matched = [flag for flag in match_any if flag in normalized]
        return matched

    def detect_trigger_groups(self, normalized: str) -> list[str]:
        trigger_synonyms = self.routing.get("normalization", {}).get("trigger_synonyms", {})

        matched_groups: list[str] = []
        for group_name, values in trigger_synonyms.items():
            if any(self._contains_phrase(normalized, value) for value in values):
                matched_groups.append(group_name)

        return matched_groups

    def detect_zone(self, normalized: str) -> str:
        zone_rules = self.routing.get("zone_rules", [])
        best_zone = "upper_gi_zone"
        best_score = -1

        for rule in zone_rules:
            zone = str(rule.get("zone", "upper_gi_zone"))
            symptoms = rule.get("if_any_symptoms", [])
            score = 0
            for symptom in symptoms:
                if self._contains_phrase(normalized, symptom):
                    score += self._weight_for_symptom(symptom)

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
            cluster = rule.get("cluster", "")
            required_zone = rule.get("requires_zone")
            if required_zone and required_zone != zone:
                continue

            score = 0

            required_trigger_group = rule.get("requires_trigger_group")
            if required_trigger_group:
                if required_trigger_group not in trigger_groups:
                    continue
                score += 5

            required_any_symptoms = rule.get("requires_any_symptoms", [])
            matched_count = 0
            for symptom in required_any_symptoms:
                if self._contains_phrase(normalized, symptom):
                    matched_count += 1
                    score += self._weight_for_symptom(symptom)

            if required_any_symptoms and matched_count == 0:
                continue

            context_flags = rule.get("requires_context_flags", [])
            if "recurrent_pattern" in context_flags:
                if not context.recurrent:
                    continue
                score += 3

            if score > best_score:
                best_score = score
                best_cluster = cluster

        return best_cluster

    def rank_causes(
        self,
        *,
        normalized: str,
        zone: str,
        cluster: str,
        trigger_groups: list[str],
        recurrent: bool,
    ) -> list[str]:
        cluster_data = self.super_master.get("symptom_clusters", {}).get(cluster, {})
        ranked = list(cluster_data.get("ranked_causes", []))

        if not ranked:
            ranked = self._fallback_causes_for_zone(zone)

        # Apply overrides
        for override in self.routing.get("cause_ranking_overrides", []):
            if self._override_matches(override, normalized, trigger_groups):
                for cause_id in override.get("promote", []):
                    ranked = self._promote_cause(ranked, cause_id)

        # Guardrails
        if not recurrent:
            ranked = [c for c in ranked if c != "ibs_pattern_if_recurrent"]

        if "histamine_like" not in trigger_groups:
            ranked = [c for c in ranked if c != "histamine_conditional_pattern"]

        if not any(flag in normalized for flag in ["боль в спину", "многократная рвота", "температура"]):
            ranked = [c for c in ranked if c != "pancreatic_warning_if_severe"]

        # Lightweight scoring by trigger compatibility
        scored: list[tuple[str, int]] = []
        for cause_id in ranked:
            score = 0
            cause = self.causes_map.get(cause_id, {})
            title = str(cause.get("title", ""))
            if "желч" in title and "fatty_fried" in trigger_groups:
                score += 2
            if "молоч" in title and "dairy" in trigger_groups:
                score += 3
            if "гистамин" in title and "histamine_like" in trigger_groups:
                score += 3
            if "глюкоз" in title and "sweet_load" in trigger_groups:
                score += 3
            if "рефлюкс" in title and any(k in normalized for k in ["изжога", "жжение", "кислая отрыжка"]):
                score += 3
            if "диспепс" in title and any(k in normalized for k in ["тяжесть", "переполненность", "тошнота"]):
                score += 2
            scored.append((cause_id, score))

        ranked = [cause_id for cause_id, _ in sorted(scored, key=lambda x: x[1], reverse=True)]
        ranked = list(dict.fromkeys(ranked))
        return ranked[:5]

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

            if_any_causes = set(rule.get("if_any_causes", []))
            if if_any_causes and if_any_causes.intersection(ranked_causes):
                recommendations.extend(rule.get("recommend", []))

        return list(dict.fromkeys(recommendations))

    @staticmethod
    def _contains_phrase(text: str, phrase: str) -> bool:
        return phrase.lower() in text.lower()

    @staticmethod
    def _promote_cause(ranked: list[str], cause_id: str) -> list[str]:
        if cause_id in ranked:
            ranked.remove(cause_id)
        ranked.insert(0, cause_id)
        return ranked

    @staticmethod
    def _weight_for_symptom(symptom: str) -> int:
        heavy = {
            "боль справа под рёбрами": 4,
            "кислая отрыжка": 4,
            "хуже лёжа": 4,
            "диарея": 4,
            "рвота": 4,
            "температура": 4,
            "изжога": 4,
            "жжение": 4,
            "вздутие": 3,
            "урчание": 3,
            "газы": 3,
            "слабость": 3,
            "головокружение": 3,
            "головная боль": 3,
            "тяжесть": 2,
            "тошнота": 2,
            "отрыжка": 2,
            "сонливость": 2,
        }
        return heavy.get(symptom, 1)

    @staticmethod
    def _override_matches(
        override: dict[str, Any],
        normalized: str,
        trigger_groups: list[str],
    ) -> bool:
        group = override.get("if_trigger_group")
        if group and group not in trigger_groups:
            return False

        required_symptoms = override.get("if_any_symptoms", [])
        if required_symptoms and not any(symptom in normalized for symptom in required_symptoms):
            return False

        return True

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

