from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ClarifyingQuestionResult:
    should_ask: bool
    questions: list[str]
    reason: str


class ClarifyingQuestionEngine:
    """
    Asks only a few targeted questions when the case is too ambiguous
    and there are no urgent red flags.
    """

    def __init__(self, super_master: dict) -> None:
        self.super_master = super_master

    def decide(
        self,
        *,
        zone: str,
        cluster: str,
        ranked_causes: list[str],
        recurrent: bool,
        matched_red_flags: list[str],
    ) -> ClarifyingQuestionResult:
        if matched_red_flags:
            return ClarifyingQuestionResult(False, [], "urgent case")

        if ranked_causes and len(ranked_causes) >= 2:
            top_two = ranked_causes[:2]
            if self._is_ambiguous_pair(zone, top_two):
                return ClarifyingQuestionResult(
                    should_ask=True,
                    questions=self._questions_for_zone(zone, recurrent),
                    reason=f"ambiguous top causes: {top_two}",
                )

        if cluster in {
            "upper_abdominal_heaviness_after_food",
            "sleepiness_weakness_after_heavy_meal",
        } and not recurrent:
            return ClarifyingQuestionResult(
                should_ask=True,
                questions=self._questions_for_zone(zone, recurrent),
                reason="generic cluster with limited specificity",
            )

        return ClarifyingQuestionResult(False, [], "enough signal")

    @staticmethod
    def _is_ambiguous_pair(zone: str, top_two: list[str]) -> bool:
        ambiguous_sets = {
            "upper_gi_zone": {
                frozenset({"functional_dyspepsia", "fatty_food_overload"}),
                frozenset({"functional_dyspepsia", "reflux_pattern"}),
                frozenset({"biliary_pattern", "fatty_food_overload"}),
            },
            "bowel_zone": {
                frozenset({"dairy_lactose_pattern", "fodmap_fermentation_pattern"}),
                frozenset({"fodmap_fermentation_pattern", "simple_overeating_or_fast_eating"}),
            },
            "systemic_zone": {
                frozenset({"postprandial_vascular_pattern", "fatty_food_systemic_overload"}),
                frozenset({"postprandial_vascular_pattern", "sugar_glucose_pattern"}),
            },
        }
        return frozenset(top_two) in ambiguous_sets.get(zone, set())

    @staticmethod
    def _questions_for_zone(zone: str, recurrent: bool) -> list[str]:
        if zone == "right_upper_abdominal_zone":
            return [
                "Где именно сильнее ощущается дискомфорт: справа под рёбрами или по центру живота?",
                "Есть ли горечь во рту, рвота или отдаёт ли боль в спину?",
            ]

        if zone == "upper_gi_zone":
            return [
                "Есть ли жжение, кислый привкус или хуже, когда ложитесь?",
                "Это больше тяжесть после еды или именно боль?",
            ]

        if zone == "bowel_zone":
            return [
                "Было ли это после молочного, сладкого или продуктов вроде лука, чеснока, бобовых?",
                "Это разовый эпизод или такое уже повторялось?",
            ]

        if zone == "systemic_zone":
            return [
                "Это было после жирной еды, сладкого или алкоголя?",
                "Есть ли слабость без боли в животе, потливость или дрожь?",
            ]

        return [
            "Где именно основной дискомфорт?",
            "Это разовый эпизод или уже повторялось?",
        ]

