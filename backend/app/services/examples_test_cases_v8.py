from __future__ import annotations

from app.services.care_plan_generator import CarePlanGenerator
from app.services.doctor_report_formatter import DoctorReportFormatter
from app.services.final_consultation_serializer import FinalConsultationSerializer
from app.services.food_journal_analyzer import FoodJournalAnalyzer
from app.services.food_router_v6 import FoodRoutingContext, FoodSymptomRouterV6
from app.services.food_rules_loader import FoodRulesLoader
from app.services.lab_mapping_bridge import LabMappingBridge
from app.services.patient_report_formatter import PatientReportFormatter
from app.services.severity_normalizer import SeverityNormalizer
from app.services.timeline_extractor import TimelineExtractor
from app.services.trigger_memory import TriggerMemoryState


def main() -> None:
    configs = FoodRulesLoader("app/knowledge").load_all()
    router = FoodSymptomRouterV6(configs)
    memory = TriggerMemoryState()

    patient_formatter = PatientReportFormatter()
    doctor_formatter = DoctorReportFormatter()
    care_plan_generator = CarePlanGenerator()
    severity_normalizer = SeverityNormalizer()
    timeline_extractor = TimelineExtractor()
    journal_analyzer = FoodJournalAnalyzer()
    lab_bridge = LabMappingBridge()
    serializer = FinalConsultationSerializer()

    user_text = "После жирной еды через час мутит, тянет справа под ребром и горечь во рту. Такое уже повторялось."
    result = router.route(
        user_text,
        context=FoodRoutingContext(
            recurrent=True,
            debug=True,
            doctor_safe=True,
            ask_followups=True,
            memory_state=memory,
        ),
    )

    memory = result["memory_state"]
    _ = memory

    patient_text = patient_formatter.format(result)
    doctor_text = doctor_formatter.format(result["doctor_safe"])
    care_plan = care_plan_generator.generate(result)

    severity = severity_normalizer.evaluate(user_text.lower())
    timeline = timeline_extractor.extract(user_text.lower())

    journal = journal_analyzer.analyze(
        [
            {"food_items": ["жирная еда"], "symptoms": ["тошнота", "горечь"]},
            {"food_items": ["жареное"], "symptoms": ["тошнота", "тяжесть справа"]},
            {"food_items": ["жирная еда"], "symptoms": ["тошнота", "горечь"]},
        ]
    )

    bridge = lab_bridge.map(
        ranked_causes=result["doctor_safe"].get("ranked_causes", []),
        recurrent=True,
        care_level=result.get("care_level", ""),
    )

    final_package = serializer.serialize(
        patient_text=patient_text,
        doctor_report=result["doctor_safe"],
        care_level=result.get("care_level", ""),
        confidence=result["doctor_safe"].get("confidence", {}),
        severity={
            "score": severity.severity_score,
            "level": severity.severity_level,
            "reasons": severity.reasons,
        },
        timeline={
            "onset_timing": timeline.onset_timing,
            "duration_hint": timeline.duration_hint,
            "timeline_clues": timeline.timeline_clues,
        },
        journal_summary={
            "repeated_foods": journal.repeated_foods,
            "repeated_symptoms": journal.repeated_symptoms,
            "likely_trigger_pairs": journal.likely_trigger_pairs,
            "summary_text": journal.summary_text,
        },
        lab_bridge={
            "suggested_lab_modules": bridge.suggested_lab_modules,
            "suggested_tests": bridge.suggested_tests,
            "rationale": bridge.rationale,
        },
    )

    print("\nPATIENT REPORT:\n")
    print(patient_text)

    print("\nDOCTOR REPORT:\n")
    print(doctor_text)

    print("\nCARE PLAN:\n")
    print(care_plan)

    print("\nFINAL PACKAGE:\n")
    print(final_package)


if __name__ == "__main__":
    main()

