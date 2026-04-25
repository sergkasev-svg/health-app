from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.confidence_engine import ConfidenceEngine
from app.services.consultation_schema import CONSULTATION_JSON_SCHEMA
from app.services.evidence_builder import EvidenceBuilder
from app.services.followup_selector import FollowupSelector
from app.services.food_response_builder import (
    build_patient_safe_response,
    build_urgent_response,
)
from app.services.medical_guardrails import MedicalGuardrails
from app.services.symptom_extractor import SymptomExtractor
from app.services.text_matchers import normalize_text
from app.services.trigger_extractor import TriggerExtractor
from app.services.trigger_memory import TriggerMemoryState


@dataclass
class FoodRoutingContext:
    recurrent: bool = False
    debug: bool = False
    doctor_safe: bool = False
    ask_followups: bool = True
    memory_state: TriggerMemoryState | None = None
    extra_flags: dict[str, Any] = field(default_factory=dict)


class FoodSymptomRouterV5:
    """
    v5:
    - trigger memory
    - confidence engine
    - follow-up selector
    - unified consultation JSON
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
        self.confidence_engine = ConfidenceEngine()
        self.followup_selector = FollowupSelector()

    def route(self, user_input: str, context: FoodRoutingContext | None = None) -> dict[str, Any]:
        context = context or FoodRoutingContext()
        memory = context.memory_state or TriggerMemoryState()
        normalized = normalize_text(user_input)

        guard = self.guardrails.check(normalized)
        if guard.is_urgent:
            patient_response = build_urgent_response(
                matched_red_flags=guard.matched_red_flags,
                urgent_reason=guard.urgent_reason,
            )

            consultation_json = {
                "mode": "urgent",
                "normalized_input": normalized,
                "zone": "urgent_route",
                "cluster": "urgent_route",
                "trigger_groups": [],
                "matched_red_flags": guard.matched_red_flags,
                "ranked_causes": ["urgent_general_route"],
                "cause_scores": {"urgent_general_route": 100},
                "evidence_by_cause": {"urgent_general_route": ["matched urgent red flags"]},
                "confidence": {
                    "score": 95,
                    "level": "high",
                    "reasons": ["urgent red flags detected"],
                },
                "recommended_tests_if_recurrent": [],
                "clarifying_questions": [],
                "memory_summary": memory.summary(),
                "patient_text": patient_response["text"],
            }

            result = dict(patient_response)
            if context.doctor_safe:
                result["doctor_safe"] = consultation_json
            if context.debug:
                result["debug"] = {
                    "consultation_json_schema": CONSULTATION_JSON_SCHEMA,
                    "consultation_json": consultation_json,
                }
            return result

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

        cause_scores = {cause_id: event.score for cause_id, event in evidence.items()}
        ranked_causes = list(cause_scores.keys())[:5]
        evidence_map = {cause_id: event.evidence for cause_id, event in evidence.items()}

        repeated_trigger_groups = memory.repeated_trigger_groups()
        repeated_causes = memory.repeated_causes()

        confidence = self.confidence_engine.evaluate(
            matched_red_flags=[],
            trigger_groups=trigger_result.trigger_groups,
            zone_scores=symptom_result.zone_scores,
            cluster_scores=symptom_result.cluster_scores,
            cause_scores=cause_scores,
            evidence_map=evidence_map,
            repeated_trigger_groups=repeated_trigger_groups,
            repeated_causes=repeated_causes,
        )

        followups: list[str] = []
        if context.ask_followups:
            followup_result = self.followup_selector.select(
                zone=symptom_result.detected_zone,
                cluster=symptom_result.detected_cluster,
                ranked_causes=ranked_causes,
                evidence_map=evidence_map,
                confidence_level=confidence.level,
                recurrent=context.recurrent,
                matched_red_flags=[],
            )
            if followup_result.should_ask:
                followups = followup_result.questions[:3]

        template_name = self._select_template(symptom_result.detected_cluster)
        recommended_tests = self._select_tests(ranked_causes, recurrent=context.recurrent)

        patient_response = build_patient_safe_response(
            template_name=template_name,
            templates=self.templates,
            ranked_cause_ids=ranked_causes,
            causes_map=self.causes_map,
            recommended_tests=recommended_tests,
            recurrent=context.recurrent,
            clarifying_questions=followups,
        )

        # Store memory after successful non-urgent reasoning.
        memory.add_event(
            trigger_groups=trigger_result.trigger_groups,
            ranked_causes=ranked_causes,
            zone=symptom_result.detected_zone,
            cluster=symptom_result.detected_cluster,
            user_text=normalized,
        )

        consultation_json = {
            "mode": "doctor_safe",
            "normalized_input": normalized,
            "zone": symptom_result.detected_zone,
            "cluster": symptom_result.detected_cluster,
            "trigger_groups": trigger_result.trigger_groups,
            "matched_red_flags": [],
            "ranked_causes": ranked_causes,
            "cause_scores": cause_scores,
            "evidence_by_cause": evidence_map,
            "confidence": {
                "score": confidence.score,
                "level": confidence.level,
                "reasons": confidence.reasons,
            },
            "recommended_tests_if_recurrent": recommended_tests,
            "clarifying_questions": followups,
            "memory_summary": memory.summary(),
            "patient_text": patient_response["text"],
        }

        result = dict(patient_response)
        result["memory_state"] = memory

        if context.doctor_safe:
            result["doctor_safe"] = consultation_json
        if context.debug:
            result["debug"] = {
                "consultation_json_schema": CONSULTATION_JSON_SCHEMA,
                "consultation_json": consultation_json,
            }

        return result

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

