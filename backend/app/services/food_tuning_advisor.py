from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TuningSuggestion:
    priority: str
    category: str
    target: str
    action: str
    rationale: str
    suggested_patch: dict[str, Any]


@dataclass
class TuningAdviceResult:
    summary: dict[str, Any]
    suggestions: list[TuningSuggestion]


class FoodTuningAdvisor:
    """
    Builds tuning suggestions from FoodFailureAnalyzer output.

    Expected input:
        analysis_result: FailureAnalysisResult
    or dict with keys:
        - summary
        - zone_confusions
        - underestimated_causes
        - overestimated_causes
        - care_level_issues
        - hypotheses
    """

    def advise(self, analysis_result: Any) -> TuningAdviceResult:
        data = self._normalize_input(analysis_result)

        suggestions: list[TuningSuggestion] = []

        suggestions.extend(self._zone_suggestions(data))
        suggestions.extend(self._underestimated_cause_suggestions(data))
        suggestions.extend(self._overestimated_cause_suggestions(data))
        suggestions.extend(self._care_level_suggestions(data))

        suggestions = self._deduplicate_suggestions(suggestions)
        suggestions = self._sort_suggestions(suggestions)

        summary = {
            "suggestions_count": len(suggestions),
            "high_priority_count": sum(1 for s in suggestions if s.priority == "high"),
            "medium_priority_count": sum(1 for s in suggestions if s.priority == "medium"),
            "low_priority_count": sum(1 for s in suggestions if s.priority == "low"),
        }

        return TuningAdviceResult(summary=summary, suggestions=suggestions)

    def _normalize_input(self, analysis_result: Any) -> dict[str, Any]:
        if hasattr(analysis_result, "summary"):
            return {
                "summary": getattr(analysis_result, "summary", {}),
                "zone_confusions": getattr(analysis_result, "zone_confusions", []),
                "underestimated_causes": getattr(analysis_result, "underestimated_causes", []),
                "overestimated_causes": getattr(analysis_result, "overestimated_causes", []),
                "care_level_issues": getattr(analysis_result, "care_level_issues", []),
                "hypotheses": getattr(analysis_result, "hypotheses", []),
            }
        if isinstance(analysis_result, dict):
            return analysis_result
        return {
            "summary": {},
            "zone_confusions": [],
            "underestimated_causes": [],
            "overestimated_causes": [],
            "care_level_issues": [],
            "hypotheses": [],
        }

    def _zone_suggestions(self, data: dict[str, Any]) -> list[TuningSuggestion]:
        suggestions: list[TuningSuggestion] = []

        for item in data.get("zone_confusions", [])[:10]:
            expected_zone = str(item.get("expected_zone", ""))
            actual_zone = str(item.get("actual_zone", ""))
            count = int(item.get("count", 0))

            if count <= 0:
                continue

            priority = "high" if count >= 10 else "medium" if count >= 5 else "low"

            # Specific medical-food routing patterns.
            if expected_zone == "right_upper_abdominal_zone" and actual_zone in {"upper_gi_zone", "systemic_zone"}:
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="zone_routing",
                        target="right_upper_abdominal_zone",
                        action="increase_zone_weight",
                        rationale="Жалобы правого подреберья, горечи и жирной пищи недостаточно уводят в biliary/RUQ ветку.",
                        suggested_patch={
                            "boost_symptoms": [
                                "справа под ребром",
                                "справа под ребрами",
                                "справа под рёбрами",
                                "правое подреберье",
                                "горечь во рту",
                                "тянет справа",
                            ],
                            "boost_trigger_groups": ["fatty_fried"],
                            "expected_zone": "right_upper_abdominal_zone",
                            "reduce_competition_from": [actual_zone],
                        },
                    )
                )

            elif expected_zone == "upper_gi_zone" and actual_zone == "systemic_zone":
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="zone_routing",
                        target="upper_gi_zone",
                        action="increase_zone_weight",
                        rationale="ЖКТ-жалобы могут недооцениваться, когда есть слабость/дурнота, и движок уходит в systemic.",
                        suggested_patch={
                            "boost_symptoms": [
                                "тяжесть",
                                "отрыжка",
                                "переполненность",
                                "под ложечкой",
                                "верх живота",
                                "эпигастрий",
                                "жжение",
                                "кислая отрыжка",
                            ],
                            "expected_zone": "upper_gi_zone",
                            "reduce_competition_from": ["systemic_zone"],
                        },
                    )
                )

            elif expected_zone == "bowel_zone" and actual_zone in {"upper_gi_zone", "systemic_zone"}:
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="zone_routing",
                        target="bowel_zone",
                        action="increase_zone_weight",
                        rationale="Кишечные сигналы могут недобирать вес в смешанных жалобах.",
                        suggested_patch={
                            "boost_symptoms": ["вздутие", "урчание", "газы", "понос", "диарея", "жидкий стул", "бурлит", "крутит живот"],
                            "expected_zone": "bowel_zone",
                            "reduce_competition_from": [actual_zone],
                        },
                    )
                )

            elif expected_zone == "systemic_zone" and actual_zone == "upper_gi_zone":
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="zone_routing",
                        target="systemic_zone",
                        action="increase_zone_weight",
                        rationale="Слабость, дрожь, потливость, дурнота и сонливость могут недооцениваться и ошибочно уходить в GI.",
                        suggested_patch={
                            "boost_symptoms": ["слабость", "сонливость", "дрожь", "потливость", "дурнота", "головокружение", "головная боль"],
                            "expected_zone": "systemic_zone",
                            "reduce_competition_from": ["upper_gi_zone"],
                        },
                    )
                )

        return suggestions

    def _underestimated_cause_suggestions(self, data: dict[str, Any]) -> list[TuningSuggestion]:
        suggestions: list[TuningSuggestion] = []

        for item in data.get("underestimated_causes", [])[:15]:
            cause = str(item.get("cause", ""))
            count = int(item.get("count", 0))
            if not cause or count <= 0:
                continue

            priority = "high" if count >= 10 else "medium" if count >= 5 else "low"

            if cause == "biliary_pattern":
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="cause_scoring",
                        target="biliary_pattern",
                        action="increase_cause_weight",
                        rationale="Желчный паттерн недобирает в кейсах с жирной едой, горечью и правым подреберьем.",
                        suggested_patch={
                            "cause": "biliary_pattern",
                            "boost_evidence": [
                                "горечь во рту",
                                "справа под ребром",
                                "правое подреберье",
                                "жирная пища",
                                "после жирного",
                                "отдает в спину",
                                "лопатка",
                            ],
                            "suggested_score_delta": 3,
                        },
                    )
                )

            elif cause == "reflux_pattern":
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="cause_scoring",
                        target="reflux_pattern",
                        action="increase_cause_weight",
                        rationale="Рефлюкс может недобираться, если признаки жжения и кислоты не получают достаточного веса.",
                        suggested_patch={
                            "cause": "reflux_pattern",
                            "boost_evidence": ["изжога", "жжение", "кислая отрыжка", "хуже лежа", "хуже лёжа", "кислота во рту", "печет в груди"],
                            "suggested_score_delta": 3,
                        },
                    )
                )

            elif cause == "dairy_lactose_pattern":
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="cause_scoring",
                        target="dairy_lactose_pattern",
                        action="increase_cause_weight",
                        rationale="Молочные триггеры могут недостаточно связываться с bowel-паттерном.",
                        suggested_patch={
                            "cause": "dairy_lactose_pattern",
                            "boost_evidence": ["молоко", "мороженое", "сливки", "творог", "йогурт", "вздутие", "урчание", "жидкий стул"],
                            "suggested_score_delta": 3,
                        },
                    )
                )

            elif cause == "fodmap_fermentation_pattern":
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="cause_scoring",
                        target="fodmap_fermentation_pattern",
                        action="increase_cause_weight",
                        rationale="FODMAP/ферментация недобирает в кейсах с луком, чесноком, бобовыми и выраженным вздутием.",
                        suggested_patch={
                            "cause": "fodmap_fermentation_pattern",
                            "boost_evidence": ["лук", "чеснок", "бобовые", "фасоль", "урчание", "газы", "вздутие", "бурлит"],
                            "suggested_score_delta": 3,
                        },
                    )
                )

            elif cause == "ibs_pattern_if_recurrent":
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="cause_scoring",
                        target="ibs_pattern_if_recurrent",
                        action="increase_recurrent_weight",
                        rationale="Повторяемость и длительность паттерна могут недооцениваться.",
                        suggested_patch={
                            "cause": "ibs_pattern_if_recurrent",
                            "boost_evidence": ["часто", "уже давно", "много месяцев", "каждую неделю", "постоянно", "то понос то запор", "нестабильный стул"],
                            "recurrent_bonus_delta": 4,
                        },
                    )
                )

            elif cause == "histamine_conditional_pattern":
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="cause_scoring",
                        target="histamine_conditional_pattern",
                        action="increase_conditional_weight",
                        rationale="Гистаминовый паттерн может быть слишком консервативным даже при типичной связке триггеров и симптомов.",
                        suggested_patch={
                            "cause": "histamine_conditional_pattern",
                            "boost_evidence": ["вино", "сыр", "копчености", "копчёности", "покраснение", "жар", "сердце колотится", "заложен нос"],
                            "require_combination": True,
                            "suggested_score_delta": 4,
                        },
                    )
                )

            elif cause == "sugar_glucose_pattern":
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="cause_scoring",
                        target="sugar_glucose_pattern",
                        action="increase_cause_weight",
                        rationale="Реакция на сладкое может недобирать в смешанных жирное+сладкое кейсах.",
                        suggested_patch={
                            "cause": "sugar_glucose_pattern",
                            "boost_evidence": ["сладкое", "торт", "десерт", "дрожь", "потливость", "сахар качает", "трусит"],
                            "suggested_score_delta": 3,
                        },
                    )
                )

            elif cause == "pancreatic_warning_if_severe":
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="cause_scoring",
                        target="pancreatic_warning_if_severe",
                        action="increase_conditional_weight",
                        rationale="Настораживающий панкреатический паттерн может недобирать при боли в спину + рвоте + температуре.",
                        suggested_patch={
                            "cause": "pancreatic_warning_if_severe",
                            "boost_evidence": ["боль в спину", "многократная рвота", "температура", "сильная боль"],
                            "require_combination": True,
                            "suggested_score_delta": 4,
                        },
                    )
                )

        return suggestions

    def _overestimated_cause_suggestions(self, data: dict[str, Any]) -> list[TuningSuggestion]:
        suggestions: list[TuningSuggestion] = []

        for item in data.get("overestimated_causes", [])[:15]:
            cause = str(item.get("cause", ""))
            count = int(item.get("count", 0))
            if not cause or count <= 0:
                continue

            priority = "high" if count >= 10 else "medium" if count >= 5 else "low"

            if cause == "postprandial_vascular_pattern":
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="cause_scoring",
                        target="postprandial_vascular_pattern",
                        action="decrease_fallback_weight",
                        rationale="Сосудистая/вегетативная реакция может слишком часто становиться общим объяснением mixed cases.",
                        suggested_patch={
                            "cause": "postprandial_vascular_pattern",
                            "reduce_when": ["есть явные GI-признаки", "есть bowel symptoms", "есть RUQ symptoms"],
                            "suggested_score_delta": -2,
                        },
                    )
                )

            elif cause == "functional_dyspepsia":
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="cause_scoring",
                        target="functional_dyspepsia",
                        action="decrease_fallback_weight",
                        rationale="Диспепсия может слишком широко использоваться как fallback и перекрывать более точные паттерны.",
                        suggested_patch={
                            "cause": "functional_dyspepsia",
                            "reduce_when": ["есть яркий reflux pattern", "есть правое подреберье", "есть bowel pattern"],
                            "suggested_score_delta": -2,
                        },
                    )
                )

            elif cause == "fatty_food_systemic_overload":
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="cause_scoring",
                        target="fatty_food_systemic_overload",
                        action="narrow_trigger_scope",
                        rationale="Жирная пища может переиспользоваться как общее объяснение, даже когда нужен более конкретный branch.",
                        suggested_patch={
                            "cause": "fatty_food_systemic_overload",
                            "reduce_when": ["есть clear reflux", "есть clear biliary", "есть clear bowel pattern"],
                            "suggested_score_delta": -2,
                        },
                    )
                )

            elif cause == "urgent_general_route":
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="urgent_routing",
                        target="urgent_general_route",
                        action="tighten_red_flag_thresholds",
                        rationale="Есть риск гиперэскалации в urgent/general route на пограничных кейсах.",
                        suggested_patch={
                            "route": "urgent_general_route",
                            "require_stronger_red_flag_combinations": True,
                            "review_red_flags": ["температура", "сильная боль", "рвота", "черный стул", "кровь", "одышка", "боль в груди"],
                        },
                    )
                )

            elif cause == "simple_overeating":
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="cause_scoring",
                        target="simple_overeating",
                        action="decrease_fallback_weight",
                        rationale="Переедание может слишком часто объяснять кейсы, где уже есть специфические признаки.",
                        suggested_patch={
                            "cause": "simple_overeating",
                            "reduce_when": ["есть молочный trigger", "есть RUQ pattern", "есть reflux clues", "есть glucose clues"],
                            "suggested_score_delta": -2,
                        },
                    )
                )

        return suggestions

    def _care_level_suggestions(self, data: dict[str, Any]) -> list[TuningSuggestion]:
        suggestions: list[TuningSuggestion] = []

        for item in data.get("care_level_issues", [])[:10]:
            expected_levels = list(item.get("expected_care_any", []))
            actual_care = str(item.get("actual_care", ""))
            count = int(item.get("count", 0))
            if count <= 0:
                continue

            priority = "high" if count >= 10 else "medium" if count >= 5 else "low"

            if "routine_doctor" in expected_levels and actual_care == "home":
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="care_level",
                        target="routine_doctor_threshold",
                        action="lower_threshold_for_recurrent_cases",
                        rationale="Повторяемые кейсы могут слишком часто оставаться в home вместо routine_doctor.",
                        suggested_patch={
                            "if_recurrent": True,
                            "increase_care_level_to": "routine_doctor",
                            "conditions": ["low_or_medium_specificity", "repeated_pattern", "repeated_trigger_group"],
                        },
                    )
                )

            elif "home" in expected_levels and actual_care in {"urgent", "emergency"}:
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="care_level",
                        target="urgent_threshold",
                        action="reduce_overtriage",
                        rationale="Есть признаки избыточной эскалации на неопасных кейсах.",
                        suggested_patch={
                            "decrease_urgent_bias": True,
                            "require_more_specific_red_flags": True,
                        },
                    )
                )

            elif "urgent" in expected_levels and actual_care == "home":
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="care_level",
                        target="urgent_threshold",
                        action="increase_urgent_sensitivity",
                        rationale="Некоторые потенциально опасные кейсы недоэскалируются.",
                        suggested_patch={
                            "increase_urgent_bias_for": ["температура+рвота", "сильная боль", "желтуха", "боль в груди", "одышка", "черный стул"],
                        },
                    )
                )

            elif "emergency" in expected_levels and actual_care in {"home", "routine_doctor"}:
                suggestions.append(
                    TuningSuggestion(
                        priority=priority,
                        category="care_level",
                        target="emergency_threshold",
                        action="increase_emergency_sensitivity",
                        rationale="Есть риск пропуска действительно опасных сценариев.",
                        suggested_patch={
                            "force_emergency_on": ["обморок", "кровь в рвоте", "кровь в стуле", "черный стул", "боль в груди", "одышка", "спутанность"],
                        },
                    )
                )

        return suggestions

    def _deduplicate_suggestions(self, suggestions: list[TuningSuggestion]) -> list[TuningSuggestion]:
        seen: set[tuple[str, str, str, str]] = set()
        deduped: list[TuningSuggestion] = []

        for s in suggestions:
            key = (s.category, s.target, s.action, s.rationale)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(s)

        return deduped

    def _sort_suggestions(self, suggestions: list[TuningSuggestion]) -> list[TuningSuggestion]:
        priority_order = {"high": 0, "medium": 1, "low": 2}
        return sorted(
            suggestions,
            key=lambda s: (priority_order.get(s.priority, 99), s.category, s.target),
        )


def print_tuning_advice(result: TuningAdviceResult) -> None:
    print("\n================ TUNING SUMMARY ================")
    for k, v in result.summary.items():
        print(f"{k}: {v}")

    print("\n================ SUGGESTIONS ===================")
    if not result.suggestions:
        print("No tuning suggestions")
        return

    for idx, s in enumerate(result.suggestions, start=1):
        print(f"\n--- Suggestion #{idx} ---")
        print("priority:", s.priority)
        print("category:", s.category)
        print("target:", s.target)
        print("action:", s.action)
        print("rationale:", s.rationale)
        print("suggested_patch:", s.suggested_patch)


if __name__ == "__main__":
    from app.services.food_failure_analyzer import FoodFailureAnalyzer
    from app.services.food_regression_scoreboard import FoodRegressionScoreboard
    from app.services.food_consultation_engine import FoodConsultationEngine

    engine = FoodConsultationEngine()
    scoreboard = FoodRegressionScoreboard(engine)
    scoreboard_result = scoreboard.run()

    analyzer = FoodFailureAnalyzer()
    analysis = analyzer.analyze(scoreboard_result)

    advisor = FoodTuningAdvisor()
    advice = advisor.advise(analysis)

    print_tuning_advice(advice)

