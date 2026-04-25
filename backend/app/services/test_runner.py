from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.services.regression_cases_food import REGRESSION_CASES_FOOD
from app.services.trigger_memory import TriggerMemoryState


@dataclass
class RegressionResult:
    total: int
    passed: int
    failed: int
    details: list[dict[str, Any]]


class FoodRegressionRunner:
    """
    Runs regression checks against router v6.
    """

    def __init__(self, router: Any, context_factory: Callable[..., Any]) -> None:
        self.router = router
        self.context_factory = context_factory

    def run(self) -> RegressionResult:
        details: list[dict[str, Any]] = []
        passed = 0
        memory = TriggerMemoryState()

        for case in REGRESSION_CASES_FOOD:
            result = self.router.route(
                case["text"],
                context=self.context_factory(
                    recurrent=case["recurrent"],
                    debug=True,
                    doctor_safe=True,
                    ask_followups=True,
                    memory_state=memory,
                ),
            )

            if "memory_state" in result:
                memory = result["memory_state"]

            doctor_safe = result.get("doctor_safe", {}) or {}
            zone = doctor_safe.get("zone", "urgent_route" if result.get("mode") == "urgent" else "")
            ranked_causes = doctor_safe.get("ranked_causes", [])
            care_level = result.get("care_level") or doctor_safe.get("care_level", {}).get("level", "")

            zone_ok = zone == case["expected_zone"]
            cause_ok = any(cause in ranked_causes for cause in case["expected_top_causes_any"])
            care_ok = care_level in case["expected_care_level_any"]

            ok = zone_ok and cause_ok and care_ok
            if ok:
                passed += 1

            details.append(
                {
                    "id": case["id"],
                    "ok": ok,
                    "zone_ok": zone_ok,
                    "cause_ok": cause_ok,
                    "care_ok": care_ok,
                    "actual_zone": zone,
                    "actual_ranked_causes": ranked_causes,
                    "actual_care_level": care_level,
                }
            )

        total = len(REGRESSION_CASES_FOOD)
        return RegressionResult(
            total=total,
            passed=passed,
            failed=total - passed,
            details=details,
        )

