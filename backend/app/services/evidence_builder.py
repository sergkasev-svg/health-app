from __future__ import annotations

from dataclasses import dataclass

from app.services.text_matchers import contains_phrase, match_any


@dataclass
class CauseEvidence:
    cause_id: str
    score: int
    evidence: list[str]


class EvidenceBuilder:
    """
    Scores causes and explains why each cause was promoted.
    """

    def __init__(self, super_master: dict, routing: dict) -> None:
        self.super_master = super_master
        self.routing = routing
        self.causes_map: dict[str, dict] = {
            cause["id"]: cause
            for cause in self.super_master.get("causes", [])
            if isinstance(cause, dict) and "id" in cause
        }

    def build(
        self,
        *,
        normalized_text: str,
        zone: str,
        cluster: str,
        trigger_groups: list[str],
        recurrent: bool,
    ) -> dict[str, CauseEvidence]:
        cause_scores: dict[str, int] = {}
        cause_evidence: dict[str, list[str]] = {}

        cluster_data = self.super_master.get("symptom_clusters", {}).get(cluster, {})
        base_causes = list(cluster_data.get("ranked_causes", []))
        if not base_causes:
            base_causes = self._fallback_causes_for_zone(zone)

        for idx, cause_id in enumerate(base_causes):
            self._add_score(
                cause_scores,
                cause_evidence,
                cause_id,
                max(12 - idx * 2, 2),
                f"base cluster ranking: {cluster}",
            )

        for cause_id in list(cause_scores.keys()):
            cause = self.causes_map.get(cause_id, {})
            title = str(cause.get("title", "")).lower()

            typical_symptoms = cause.get("typical_symptoms", [])
            matched_symptoms = match_any(normalized_text, typical_symptoms, allow_fuzzy=True, threshold=0.86)
            if matched_symptoms:
                self._add_score(
                    cause_scores,
                    cause_evidence,
                    cause_id,
                    len(matched_symptoms) * 2,
                    f"matched symptoms: {', '.join(matched_symptoms)}",
                )

            when_to_raise = cause.get("when_to_raise", [])
            matched_raise = match_any(normalized_text, when_to_raise, allow_fuzzy=True, threshold=0.86)
            if matched_raise:
                self._add_score(
                    cause_scores,
                    cause_evidence,
                    cause_id,
                    len(matched_raise) * 2,
                    f"raise clues: {', '.join(matched_raise)}",
                )

            if "молоч" in title and "dairy" in trigger_groups:
                self._add_score(cause_scores, cause_evidence, cause_id, 5, "trigger compatibility: dairy")
            if "гистамин" in title and "histamine_like" in trigger_groups:
                self._add_score(cause_scores, cause_evidence, cause_id, 6, "trigger compatibility: histamine_like")
            if "глюкоз" in title and "sweet_load" in trigger_groups:
                self._add_score(cause_scores, cause_evidence, cause_id, 6, "trigger compatibility: sweet_load")
            if "желч" in title and "fatty_fried" in trigger_groups:
                self._add_score(cause_scores, cause_evidence, cause_id, 5, "trigger compatibility: fatty_fried")
            if "рефлюкс" in title and self._has_any(
                normalized_text, ["изжога", "жжение", "кислая отрыжка", "хуже лежа", "хуже лёжа"]
            ):
                self._add_score(cause_scores, cause_evidence, cause_id, 6, "pattern fit: reflux-like")
            if "диспепс" in title and self._has_any(
                normalized_text, ["тяжесть", "переполненность", "тошнота", "отрыжка"]
            ):
                self._add_score(cause_scores, cause_evidence, cause_id, 5, "pattern fit: dyspepsia-like")

        for override in self.routing.get("cause_ranking_overrides", []):
            if self._override_matches(override, normalized_text, trigger_groups):
                for cause_id in override.get("promote", []):
                    self._add_score(cause_scores, cause_evidence, cause_id, 8, "override promotion rule")

        if not recurrent and "ibs_pattern_if_recurrent" in cause_scores:
            cause_scores.pop("ibs_pattern_if_recurrent", None)
            cause_evidence.pop("ibs_pattern_if_recurrent", None)

        if "histamine_like" not in trigger_groups and "histamine_conditional_pattern" in cause_scores:
            cause_scores.pop("histamine_conditional_pattern", None)
            cause_evidence.pop("histamine_conditional_pattern", None)

        if not self._has_any(normalized_text, ["боль в спину", "многократная рвота", "температура", "сильная боль"]):
            cause_scores.pop("pancreatic_warning_if_severe", None)
            cause_evidence.pop("pancreatic_warning_if_severe", None)

        ranked = dict(sorted(cause_scores.items(), key=lambda x: x[1], reverse=True))

        result: dict[str, CauseEvidence] = {}
        for cause_id, score in ranked.items():
            result[cause_id] = CauseEvidence(
                cause_id=cause_id,
                score=score,
                evidence=cause_evidence.get(cause_id, []),
            )
        return result

    @staticmethod
    def _add_score(
        cause_scores: dict[str, int],
        cause_evidence: dict[str, list[str]],
        cause_id: str,
        score: int,
        evidence: str,
    ) -> None:
        cause_scores[cause_id] = cause_scores.get(cause_id, 0) + score
        cause_evidence.setdefault(cause_id, []).append(evidence)

    @staticmethod
    def _override_matches(
        override: dict,
        normalized_text: str,
        trigger_groups: list[str],
    ) -> bool:
        trigger_group = override.get("if_trigger_group")
        if trigger_group and trigger_group not in trigger_groups:
            return False

        required_symptoms = override.get("if_any_symptoms", [])
        if required_symptoms and not match_any(normalized_text, required_symptoms, allow_fuzzy=True, threshold=0.88):
            return False

        return True

    @staticmethod
    def _has_any(normalized_text: str, phrases: list[str]) -> bool:
        return any(contains_phrase(normalized_text, phrase) for phrase in phrases)

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

