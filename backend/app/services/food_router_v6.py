from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.care_level_engine import CareLevelEngine
from app.services.confidence_engine import ConfidenceEngine
from app.services.consultation_schema import CONSULTATION_JSON_SCHEMA
from app.services.evidence_builder import EvidenceBuilder
from app.services.followup_selector import FollowupSelector
from app.services.medical_guardrails import MedicalGuardrails
from app.services.recommendation_engine import RecommendationEngine
from app.services.report_builder import ReportBuilder
from app.services.rule_registry import RuleRegistry
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


class FoodSymptomRouterV6:
    """
    v6:
    - care level engine
    - recommendation engine
    - report builder
    - rule registry
    - unified consultation package
    """

    def __init__(self, configs: dict[str, Any]) -> None:
        self.super_master = configs["super_master"]
        self.templates = configs["templates"]
        self.routing = configs["routing"]

        self.registry = RuleRegistry(
            super_master=self.super_master,
            routing=self.routing,
            templates=self.templates,
        )

        self.guardrails = MedicalGuardrails(self.routing)
        self.symptom_extractor = SymptomExtractor(self.routing)
        self.trigger_extractor = TriggerExtractor(self.routing)
        self.evidence_builder = EvidenceBuilder(self.super_master, self.routing)
        self.confidence_engine = ConfidenceEngine()
        self.followup_selector = FollowupSelector()
        self.care_level_engine = CareLevelEngine()
        self.recommendation_engine = RecommendationEngine()
        self.report_builder = ReportBuilder()

    def route(self, user_input: str, context: FoodRoutingContext | None = None) -> dict[str, Any]:
        context = context or FoodRoutingContext()
        memory = context.memory_state or TriggerMemoryState()
        normalized = normalize_text(user_input)

        guard = self.guardrails.check(normalized)
        if guard.is_urgent:
            care = self.care_level_engine.evaluate(
                matched_red_flags=guard.matched_red_flags,
                ranked_causes=["urgent_general_route"],
                confidence_level="high",
                recurrent=context.recurrent,
            )

            recommendations = self.recommendation_engine.build(
                ranked_causes=["urgent_general_route"],
                care_level=care.level,
                recurrent=context.recurrent,
                recommended_tests=[],
            )

            report = self.report_builder.build(
                normalized_input=normalized,
                zone="urgent_route",
                cluster="urgent_route",
                ranked_causes=["urgent_general_route"],
                cause_scores={"urgent_general_route": 100},
                evidence_by_cause={"urgent_general_route": ["matched urgent red flags"]},
                confidence={
                    "score": 95,
                    "level": "high",
                    "reasons": ["urgent red flags detected"],
                },
                care_level={
                    "level": care.level,
                    "reason": care.reason,
                    "action_hint": care.action_hint,
                },
                recommendations={
                    "do_now": recommendations.do_now,
                    "avoid_now": recommendations.avoid_now,
                    "tests_if_recurrent": recommendations.tests_if_recurrent,
                    "followup_advice": recommendations.followup_advice,
                },
                followup_questions=[],
                memory_summary=memory.summary(),
            )

            consultation_package = {
                "mode": "urgent",
                "consultation_json_schema": CONSULTATION_JSON_SCHEMA,
                "consultation_json": {
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
                    "patient_text": report.patient_text,
                },
            }

            result = {
                "mode": "urgent",
                "text": report.patient_text,
                "memory_state": memory,
            }
            if context.doctor_safe:
                result["doctor_safe"] = report.doctor_report
            if context.debug:
                result["debug"] = consultation_package
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

        cause_scores = {cause_id: evidence_item.score for cause_id, evidence_item in evidence.items()}
        ranked_causes = list(cause_scores.keys())[:5]
        evidence_map = {cause_id: evidence_item.evidence for cause_id, evidence_item in evidence.items()}

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

        recommended_tests = self._select_tests(ranked_causes, recurrent=context.recurrent)

        care = self.care_level_engine.evaluate(
            matched_red_flags=[],
            ranked_causes=ranked_causes,
            confidence_level=confidence.level,
            recurrent=context.recurrent,
        )

        recommendations = self.recommendation_engine.build(
            ranked_causes=ranked_causes,
            care_level=care.level,
            recurrent=context.recurrent,
            recommended_tests=recommended_tests,
        )

        # Update memory after non-urgent reasoning.
        memory.add_event(
            trigger_groups=trigger_result.trigger_groups,
            ranked_causes=ranked_causes,
            zone=symptom_result.detected_zone,
            cluster=symptom_result.detected_cluster,
            user_text=normalized,
        )

        report = self.report_builder.build(
            normalized_input=normalized,
            zone=symptom_result.detected_zone,
            cluster=symptom_result.detected_cluster,
            ranked_causes=ranked_causes,
            cause_scores=cause_scores,
            evidence_by_cause=evidence_map,
            confidence={
                "score": confidence.score,
                "level": confidence.level,
                "reasons": confidence.reasons,
            },
            care_level={
                "level": care.level,
                "reason": care.reason,
                "action_hint": care.action_hint,
            },
            recommendations={
                "do_now": recommendations.do_now,
                "avoid_now": recommendations.avoid_now,
                "tests_if_recurrent": recommendations.tests_if_recurrent,
                "followup_advice": recommendations.followup_advice,
            },
            followup_questions=followups,
            memory_summary=memory.summary(),
        )

        consultation_package = {
            "mode": "doctor_safe",
            "consultation_json_schema": CONSULTATION_JSON_SCHEMA,
            "consultation_json": {
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
                "recommended_tests_if_recurrent": recommendations.tests_if_recurrent,
                "clarifying_questions": followups,
                "memory_summary": memory.summary(),
                "patient_text": report.patient_text,
            },
        }

        result = {
            "mode": "patient_safe",
            "text": report.patient_text,
            "care_level": care.level,
            "memory_state": memory,
        }

        if context.doctor_safe:
            result["doctor_safe"] = report.doctor_report
        if context.debug:
            result["debug"] = consultation_package

        return result

    def _select_tests(self, ranked_causes: list[str], recurrent: bool) -> list[str]:
        if not recurrent:
            return []

        recommendations: list[str] = []
        for rule in self.registry.get_tests_rules():
            if not rule.get("if_recurrent", False):
                continue
            allowed_causes = set(rule.get("if_any_causes", []))
            if allowed_causes and allowed_causes.intersection(ranked_causes):
                recommendations.extend(rule.get("recommend", []))
        return list(dict.fromkeys(recommendations))

