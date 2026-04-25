from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.clarifying_question_engine import ClarifyingQuestionEngine
from app.services.evidence_builder import EvidenceBuilder
from app.services.food_response_builder import (
    build_doctor_safe_output,
    build_patient_safe_response,
    build_urgent_response,
)
from app.services.medical_guardrails import MedicalGuardrails
from app.services.reasoning_debug import make_reasoning_debug_payload
from app.services.symptom_extractor import SymptomExtractor
from app.services.text_matchers import normalize_text
from app.services.trigger_extractor import TriggerExtractor


@dataclass
class FoodRoutingContext:
    recurrent: bool = False
    debug: bool = False
    doctor_safe: bool = False
    ask_clarifying: bool = True
    extra_flags: dict[str, Any] = field(default_factory=dict)


class FoodSymptomRouterV4:
    """
    v4 clinical-style router:
    - separate symptom extractor
    - separate trigger extractor
    - evidence builder
    - clarifying question engine
    - patient-safe + doctor-safe output
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
        self.symptom_extractor = SymptomExtractor(self.routing)
        self.trigger_extractor = TriggerExtractor(self.routing)
        self.evidence_builder = EvidenceBuilder(self.super_master, self.routing)
        self.clarifying_engine = ClarifyingQuestionEngine(self.super_master)

    def route(self, user_input: str, context: FoodRoutingContext | None = None) -> dict[str, Any]:
        context = context or FoodRoutingContext()
        normalized = normalize_text(user_input)

        guard = self.guardrails.check(normalized)
        if guard.is_urgent:
            urgent_response = build_urgent_response(
                matched_red_flags=guard.matched_red_flags,
                urgent_reason=guard.urgent_reason,
            )

            if context.doctor_safe:
                urgent_response["doctor_safe"] = build_doctor_safe_output(
                    normalized=normalized,
                    zone="urgent_route",
                    cluster="urgent_route",
                    trigger_groups=[],
                    matched_red_flags=guard.matched_red_flags,
                    cause_scores={"urgent_general_route": 100},
                    ranked_cause_ids=["urgent_general_route"],
                    recommended_tests=[],
                    recurrent=context.recurrent,
                    evidence_map={"urgent_general_route": ["matched urgent red flags"]},
                    clarifying_questions=[],
                )

            if context.debug:
                urgent_response["debug"] = make_reasoning_debug_payload(
                    normalized=normalized,
                    matched_symptoms=[],
                    zone_scores={},
                    zone="urgent_route",
                    cluster_scores={},
                    cluster="urgent_route",
                    trigger_groups=[],
                    matched_red_flags=guard.matched_red_flags,
                    cause_scores={"urgent_general_route": 100},
                    ranked_causes=["urgent_general_route"],
                    evidence_map={"urgent_general_route": ["matched urgent red flags"]},
                    recurrent=context.recurrent,
                    template="urgent_only",
                    recommended_tests=[],
                    clarifying_questions=[],
                )

            return urgent_response

        trigger_result = self.trigger_extractor.extract(normalized)
        symptom_result = self.symptom_extractor.extract(
            normalized_text=normalized,
            trigger_groups=trigger_result.trigger_groups,
            recurrent=context.recurrent,
        )

        evidence = self.evidence_builder.build(
            normalized_text=normalized,
            zone=symptom_result.detected_zone,
            cluster=symptom_result.detected_cluster,
            trigger_groups=trigger_result.trigger_groups,
            recurrent=context.recurrent,
        )

        cause_scores = {cause_id: ev.score for cause_id, ev in evidence.items()}
        ranked_causes = list(cause_scores.keys())[:5]
        evidence_map = {cause_id: ev.evidence for cause_id, ev in evidence.items()}

        template_name = self._select_template(symptom_result.detected_cluster)
        recommended_tests = self._select_tests(ranked_causes, recurrent=context.recurrent)

        clarifying_questions: list[str] = []
        if context.ask_clarifying:
            clarifying = self.clarifying_engine.decide(
                zone=symptom_result.detected_zone,
                cluster=symptom_result.detected_cluster,
                ranked_causes=ranked_causes,
                recurrent=context.recurrent,
                matched_red_flags=[],
            )
            if clarifying.should_ask:
                clarifying_questions = clarifying.questions[:3]

        response = build_patient_safe_response(
            template_name=template_name,
            templates=self.templates,
            ranked_cause_ids=ranked_causes,
            causes_map=self.causes_map,
            recommended_tests=recommended_tests,
            recurrent=context.recurrent,
            clarifying_questions=clarifying_questions,
        )

        if context.doctor_safe:
            response["doctor_safe"] = build_doctor_safe_output(
                normalized=normalized,
                zone=symptom_result.detected_zone,
                cluster=symptom_result.detected_cluster,
                trigger_groups=trigger_result.trigger_groups,
                matched_red_flags=[],
                cause_scores=cause_scores,
                ranked_cause_ids=ranked_causes,
                recommended_tests=recommended_tests,
                recurrent=context.recurrent,
                evidence_map=evidence_map,
                clarifying_questions=clarifying_questions,
            )

        if context.debug:
            response["debug"] = make_reasoning_debug_payload(
                normalized=normalized,
                matched_symptoms=symptom_result.matched_symptoms,
                zone_scores=symptom_result.zone_scores,
                zone=symptom_result.detected_zone,
                cluster_scores=symptom_result.cluster_scores,
                cluster=symptom_result.detected_cluster,
                trigger_groups=trigger_result.trigger_groups,
                matched_red_flags=[],
                cause_scores=cause_scores,
                ranked_causes=ranked_causes,
                evidence_map=evidence_map,
                recurrent=context.recurrent,
                template=template_name,
                recommended_tests=recommended_tests,
                clarifying_questions=clarifying_questions,
            )

        return response

    def _select_template(self, cluster: str) -> str:
        for rule in self.routing.get("template_selection_rules", []):
            if rule.get("if_cluster") == cluster:
                return str(rule.get("template"))
        return "base_response"

    def _select_tests(self, ranked_causes: list[str], recurrent: bool) -> list[str]:
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

