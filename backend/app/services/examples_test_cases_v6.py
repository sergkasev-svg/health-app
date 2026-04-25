from __future__ import annotations

from app.services.food_router_v6 import FoodRoutingContext, FoodSymptomRouterV6
from app.services.food_rules_loader import FoodRulesLoader
from app.services.care_plan_generator import CarePlanGenerator
from app.services.doctor_report_formatter import DoctorReportFormatter
from app.services.patient_report_formatter import PatientReportFormatter
from app.services.test_runner import FoodRegressionRunner
from app.services.trigger_memory import TriggerMemoryState


def main() -> None:
    configs = FoodRulesLoader("app/knowledge").load_all()
    router = FoodSymptomRouterV6(configs)

    patient_formatter = PatientReportFormatter()
    doctor_formatter = DoctorReportFormatter()
    care_plan_generator = CarePlanGenerator()

    memory = TriggerMemoryState()

    sample_inputs = [
        ("После жареной картошки и семечек подташнивает и болит голова", False),
        ("После молока и мороженого раздуло живот и жидкий стул", True),
        ("После жирного тянет справа под ребром и горечь во рту", True),
    ]

    for text, recurrent in sample_inputs:
        print("\n==========================")
        print("INPUT:", text)

        result = router.route(
            text,
            context=FoodRoutingContext(
                recurrent=recurrent,
                debug=True,
                doctor_safe=True,
                ask_followups=True,
                memory_state=memory,
            ),
        )

        memory = result["memory_state"]

        print("\nPATIENT REPORT:")
        print(patient_formatter.format(result))

        print("\nDOCTOR REPORT:")
        print(doctor_formatter.format(result.get("doctor_safe", {})))

        care_plan = care_plan_generator.generate(result)
        print("\nCARE PLAN:")
        print("what_to_do:", care_plan.what_to_do)
        print("what_to_avoid:", care_plan.what_to_avoid)
        print("when_to_seek_help:", care_plan.when_to_seek_help)
        print("tests_to_consider_if_recurrent:", care_plan.tests_to_consider_if_recurrent)

    print("\n==========================")
    print("RUNNING REGRESSION...")

    runner = FoodRegressionRunner(router=router, context_factory=FoodRoutingContext)
    regression = runner.run()

    print(f"TOTAL: {regression.total}")
    print(f"PASSED: {regression.passed}")
    print(f"FAILED: {regression.failed}")
    for item in regression.details:
        print(item)


if __name__ == "__main__":
    main()

