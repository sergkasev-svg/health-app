from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.food_consultation_engine import FoodConsultationEngine


@dataclass
class FailureAnalysisResult:
    summary: dict[str, Any]
    zone_confusions: list[dict[str, Any]]
    underestimated_causes: list[dict[str, Any]]
    overestimated_causes: list[dict[str, Any]]
    care_level_issues: list[dict[str, Any]]
    hypotheses: list[str]


class FoodFailureAnalyzer:
    """
    Analyzes failed regression cases from FoodRegressionScoreboard output.

    Expected input:
        scoreboard_result: ScoreboardResult
    or
        scoreboard_result_dict: {
            "overall": ...,
            "tiers": ...,
            "common_failures": ...,
            "failed_cases": [...]
        }
    """

    def analyze(self, scoreboard_result: Any) -> FailureAnalysisResult:
        failed_cases = self._extract_failed_cases(scoreboard_result)

        zone_confusions = self._analyze_zone_confusions(failed_cases)
        underestimated_causes = self._analyze_underestimated_causes(failed_cases)
        overestimated_causes = self._analyze_overestimated_causes(failed_cases)
        care_level_issues = self._analyze_care_level_issues(failed_cases)
        hypotheses = self._build_hypotheses(
            zone_confusions=zone_confusions,
            underestimated_causes=underestimated_causes,
            overestimated_causes=overestimated_causes,
            care_level_issues=care_level_issues,
        )

        summary = {
            "failed_cases_count": len(failed_cases),
            "unique_zone_confusions": len(zone_confusions),
            "unique_underestimated_causes": len(underestimated_causes),
            "unique_overestimated_causes": len(overestimated_causes),
            "unique_care_level_issues": len(care_level_issues),
        }

        return FailureAnalysisResult(
            summary=summary,
            zone_confusions=zone_confusions,
            underestimated_causes=underestimated_causes,
            overestimated_causes=overestimated_causes,
            care_level_issues=care_level_issues,
            hypotheses=hypotheses,
        )

    def _extract_failed_cases(self, scoreboard_result: Any) -> list[dict[str, Any]]:
        if hasattr(scoreboard_result, "failed_cases"):
            return list(scoreboard_result.failed_cases)
        if isinstance(scoreboard_result, dict):
            return list(scoreboard_result.get("failed_cases", []))
        return []

    def _analyze_zone_confusions(self, failed_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counter: dict[tuple[str, str], int] = {}

        for case in failed_cases:
            if case.get("zone_ok", True):
                continue
            expected_zone = str(case.get("expected_zone", ""))
            actual_zone = str(case.get("actual_zone", ""))
            key = (expected_zone, actual_zone)
            counter[key] = counter.get(key, 0) + 1

        ranked = sorted(counter.items(), key=lambda x: x[1], reverse=True)
        return [
            {
                "expected_zone": expected,
                "actual_zone": actual,
                "count": count,
            }
            for (expected, actual), count in ranked
        ]

    def _analyze_underestimated_causes(self, failed_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Underestimated cause = expected cause set not found in actual ranked causes.
        """
        counter: dict[str, int] = {}

        for case in failed_cases:
            if case.get("cause_ok", True):
                continue
            expected_causes = case.get("expected_causes_any", []) or []
            actual_causes = case.get("actual_ranked_causes", []) or []

            for cause in expected_causes:
                if cause not in actual_causes:
                    counter[cause] = counter.get(cause, 0) + 1

        ranked = sorted(counter.items(), key=lambda x: x[1], reverse=True)
        return [{"cause": cause, "count": count} for cause, count in ranked]

    def _analyze_overestimated_causes(self, failed_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Overestimated cause = actual top cause(s) appears often in failed cause mismatches
        while not being among expected causes.
        """
        counter: dict[str, int] = {}

        for case in failed_cases:
            if case.get("cause_ok", True):
                continue
            expected_causes = set(case.get("expected_causes_any", []) or [])
            actual_causes = list(case.get("actual_ranked_causes", []) or [])

            for cause in actual_causes[:3]:
                if cause not in expected_causes:
                    counter[cause] = counter.get(cause, 0) + 1

        ranked = sorted(counter.items(), key=lambda x: x[1], reverse=True)
        return [{"cause": cause, "count": count} for cause, count in ranked]

    def _analyze_care_level_issues(self, failed_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counter: dict[tuple[str, str], int] = {}

        for case in failed_cases:
            if case.get("care_ok", True):
                continue
            expected_levels = case.get("expected_care_any", []) or []
            actual_level = str(case.get("actual_care", ""))

            expected_key = "|".join(sorted(str(x) for x in expected_levels))
            key = (expected_key, actual_level)
            counter[key] = counter.get(key, 0) + 1

        ranked = sorted(counter.items(), key=lambda x: x[1], reverse=True)
        return [
            {
                "expected_care_any": expected.split("|") if expected else [],
                "actual_care": actual,
                "count": count,
            }
            for (expected, actual), count in ranked
        ]

    def _build_hypotheses(
        self,
        *,
        zone_confusions: list[dict[str, Any]],
        underestimated_causes: list[dict[str, Any]],
        overestimated_causes: list[dict[str, Any]],
        care_level_issues: list[dict[str, Any]],
    ) -> list[str]:
        hypotheses: list[str] = []

        if zone_confusions:
            top = zone_confusions[0]
            hypotheses.append(
                f"Частая путаница зон: ожидается {top['expected_zone']}, но движок уводит в {top['actual_zone']}."
            )

        if underestimated_causes:
            top = underestimated_causes[0]
            hypotheses.append(
                f"Движок недооценивает причину {top['cause']} — её часто ждут в эталоне, но она не попадает в ranking."
            )

        if overestimated_causes:
            top = overestimated_causes[0]
            hypotheses.append(
                f"Движок переоценивает причину {top['cause']} — она слишком часто попадает в top causes при провалах."
            )

        if care_level_issues:
            top = care_level_issues[0]
            expected = ", ".join(top["expected_care_any"]) if top["expected_care_any"] else "unknown"
            hypotheses.append(
                f"Есть системная проблема с care level: ожидался один из [{expected}], но часто получается {top['actual_care']}."
            )

        # Heuristic hypotheses based on common medical-food routing failure patterns.
        underestimated_names = {x["cause"] for x in underestimated_causes[:5]}
        overestimated_names = {x["cause"] for x in overestimated_causes[:5]}

        if "biliary_pattern" in underestimated_names:
            hypotheses.append("Вероятно, движок недодаёт вес правому подреберью, горечи и связи с жирной пищей.")
        if "reflux_pattern" in underestimated_names:
            hypotheses.append("Вероятно, движок недодаёт вес жжению, кислой отрыжке и ухудшению лёжа.")
        if "dairy_lactose_pattern" in underestimated_names:
            hypotheses.append("Вероятно, движок недостаточно связывает молочные триггеры с вздутием, урчанием и жидким стулом.")
        if "histamine_conditional_pattern" in underestimated_names:
            hypotheses.append("Вероятно, движок слишком осторожен по гистаминовому паттерну даже при сочетании вино/сыр + покраснение/сердцебиение.")
        if "ibs_pattern_if_recurrent" in underestimated_names:
            hypotheses.append("Вероятно, движок недодаёт вес хронической повторяемости и паттерну изменения стула.")

        if "postprandial_vascular_pattern" in overestimated_names:
            hypotheses.append("Движок может слишком часто сваливать смешанные жалобы в сосудистую/вегетативную реакцию.")
        if "fatty_food_systemic_overload" in overestimated_names:
            hypotheses.append("Движок может переобъяснять жалобы жирной пищей даже там, где нужен более конкретный GI или biliary branch.")
        if "urgent_general_route" in overestimated_names:
            hypotheses.append("Возможна переэскалация в urgent/general route на пограничных кейсах.")
        if "functional_dyspepsia" in overestimated_names:
            hypotheses.append("Движок может слишком широко использовать диспепсию как fallback, перекрывая более точные паттерны.")

        if not hypotheses:
            hypotheses.append("Явного доминирующего паттерна провалов не найдено, нужны дополнительные кейсы или более детальная телеметрия.")

        return hypotheses


def print_failure_analysis(result: FailureAnalysisResult) -> None:
    print("\n================ FAILURE SUMMARY ================")
    for k, v in result.summary.items():
        print(f"{k}: {v}")

    print("\n================ ZONE CONFUSIONS ================")
    if not result.zone_confusions:
        print("No zone confusions")
    else:
        for item in result.zone_confusions:
            print(item)

    print("\n============= UNDERESTIMATED CAUSES =============")
    if not result.underestimated_causes:
        print("No underestimated causes")
    else:
        for item in result.underestimated_causes:
            print(item)

    print("\n============= OVERESTIMATED CAUSES ==============")
    if not result.overestimated_causes:
        print("No overestimated causes")
    else:
        for item in result.overestimated_causes:
            print(item)

    print("\n============== CARE LEVEL ISSUES ================")
    if not result.care_level_issues:
        print("No care level issues")
    else:
        for item in result.care_level_issues:
            print(item)

    print("\n================== HYPOTHESES ===================")
    for item in result.hypotheses:
        print("-", item)


if __name__ == "__main__":
    from app.services.food_regression_scoreboard import FoodRegressionScoreboard

    engine = FoodConsultationEngine()
    scoreboard = FoodRegressionScoreboard(engine)
    scoreboard_result = scoreboard.run()

    analyzer = FoodFailureAnalyzer()
    analysis = analyzer.analyze(scoreboard_result)
    print_failure_analysis(analysis)

