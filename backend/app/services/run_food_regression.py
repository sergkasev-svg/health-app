from __future__ import annotations

from app.services.food_consultation_engine import FoodConsultationEngine, FoodRoutingContext, TriggerMemoryState
from app.services.food_regression_cases_200 import REGRESSION_CASES_FOOD_200


def run_regression() -> dict:
    engine = FoodConsultationEngine()
    memory = TriggerMemoryState()

    total = 0
    passed = 0
    details = []

    for case in REGRESSION_CASES_FOOD_200:
        total += 1

        result = engine.consult(
            case["text"],
            context=FoodRoutingContext(
                recurrent=case["recurrent"],
                debug=False,
                ask_followups=True,
                doctor_safe=True,
            ),
            memory_state=memory,
        )

        memory = result["memory_state"]

        doctor_view = result["doctor_view"]
        actual_zone = doctor_view.get("zone", "")
        actual_ranked_causes = doctor_view.get("ranked_causes", [])
        actual_care_level = result["patient_view"].get("care_level", "")

        zone_ok = actual_zone == case["expected_zone"]
        cause_ok = any(cause in actual_ranked_causes for cause in case["expected_top_causes_any"])
        care_ok = actual_care_level in case["expected_care_level_any"]

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
                "actual_zone": actual_zone,
                "actual_ranked_causes": actual_ranked_causes,
                "actual_care_level": actual_care_level,
            }
        )

    failed = total - passed
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "score_percent": round((passed / total) * 100, 1) if total else 0.0,
        "details": details,
    }


if __name__ == "__main__":
    result = run_regression()
    print("TOTAL:", result["total"])
    print("PASSED:", result["passed"])
    print("FAILED:", result["failed"])
    print("SCORE:", result["score_percent"], "%")
    for item in result["details"]:
        if not item["ok"]:
            print(item)

