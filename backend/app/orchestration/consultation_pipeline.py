from __future__ import annotations

from typing import Any

from app.learning.feedback_engine import process_feedback, retrain_after_n_cases
from app.orchestration.block_runner import BlockRunner
from app.orchestration.state_models import ConsultationState


class ConsultationPipeline:
    def __init__(self, runner: BlockRunner | None = None) -> None:
        self.runner = runner or BlockRunner()

    def run(
        self,
        user_input: str,
        chat_history: list[dict[str, Any]] | None = None,
        uploaded_files: list[dict[str, Any]] | None = None,
        initial_state: ConsultationState | None = None,
        confirmed_diagnosis: str | None = None,
    ) -> ConsultationState:
        state = initial_state or self.runner.init_state()

        # 0) Intake Normalizer
        intake = self.runner.run_intake_normalizer(
            user_input=user_input,
            chat_history=chat_history,
            uploaded_files=uploaded_files,
        )
        state.chief_complaint = intake.chief_complaint or state.chief_complaint
        state.history.duration = intake.history.duration or state.history.duration
        state.history.onset = intake.history.onset or state.history.onset
        state.history.location = intake.history.location or state.history.location
        state.history.severity = intake.history.severity or state.history.severity
        state.history.temperature = (
            intake.history.temperature if intake.history.temperature is not None else state.history.temperature
        )
        state.history.symptoms = list(dict.fromkeys((state.history.symptoms or []) + (intake.history.symptoms or [])))
        state.history.chronic_conditions = list(
            dict.fromkeys((state.history.chronic_conditions or []) + (intake.history.chronic_conditions or []))
        )
        state.history.medications = list(dict.fromkeys((state.history.medications or []) + (intake.history.medications or [])))
        state.history.allergies = list(dict.fromkeys((state.history.allergies or []) + (intake.history.allergies or [])))
        state.history.lifestyle = list(dict.fromkeys((state.history.lifestyle or []) + (intake.history.lifestyle or [])))
        if intake.uploaded_files:
            state.uploaded_files = intake.uploaded_files

        # 0.5) V4 Clinical Reasoning (diagnosis_candidates, differential, red_flags from text)
        if state.history.symptoms:
            try:
                candidates, differential, red_flags_text = self.runner.run_clinical_reasoning_v4(state)
                state.diagnosis_candidates = candidates
                state.differential_diagnosis = differential
                state.red_flags = list(dict.fromkeys((state.red_flags or []) + red_flags_text))
            except Exception:
                pass

        # 1) Adaptive Medical Question Engine
        adaptive = self.runner.run_adaptive_question_engine(state)
        state.red_flags = list(dict.fromkeys(adaptive.red_flags_detected))
        state.missing_data = adaptive.missing_critical_data
        state.next_question = adaptive.next_best_question

        route = self.runner.apply_adaptive_routing(adaptive)
        if route == "urgent":
            safety = self.runner.run_clinical_safety_guardrail(state)
            state.urgent_recommendation = safety.urgent_notice
            state.safe_recommendations = safety.final_safety_notes
            state.final_answer = {
                "urgent_notice": safety.urgent_notice,
                "safe_notes": safety.final_safety_notes,
                "disclaimer": safety.disclaimer,
            }
            return state
        if route == "ask_user":
            state.final_answer = {
                "status": "need_more_data",
                "next_question": adaptive.next_best_question.model_dump() if adaptive.next_best_question else None,
                "missing_critical_data": adaptive.missing_critical_data,
            }
            return state

        # 2) Lab Result Parser
        lab_parsed = self.runner.run_lab_result_parser(state)
        state.parsed_labs = lab_parsed.parsed_labs

        # 2.5) V5 Probabilistic Diagnosis (Bayesian + lab evidence)
        if state.history.symptoms:
            try:
                prob_diagnosis = self.runner.run_probabilistic_diagnosis_v5(state)
                if prob_diagnosis:
                    state.diagnosis_probabilities = prob_diagnosis
                    state.differential_diagnosis = [{"disease": x.get("disease"), "probability": x.get("probability")} for x in prob_diagnosis[:3]]
            except Exception:
                pass

        # 3) Knowledge Retrieval
        retrieval = self.runner.run_knowledge_retrieval(state)
        state.retrieved_knowledge = retrieval.retrieved_knowledge

        # 4) Medical Retrieval Ranking Engine
        ranked = self.runner.run_retrieval_ranking(state)
        state.ranked_knowledge = ranked.ranked_knowledge

        # 5) Diagnostic Reasoning Engine
        reasoning = self.runner.run_diagnostic_reasoning(state)
        state.hypotheses = reasoning.differential_hypotheses
        state.red_flags = list(dict.fromkeys(state.red_flags + reasoning.red_flags))

        # 6) Clinical Evidence Weighting Engine
        weighted = self.runner.run_evidence_weighting(state)
        state.weighted_hypotheses = weighted.weighted_hypotheses

        # recommendations from reasoning output
        state.safe_recommendations = list(dict.fromkeys(reasoning.recommended_tests + reasoning.recommended_questions))

        # 7) Clinical Safety Guardrail
        safety = self.runner.run_clinical_safety_guardrail(state)
        if safety.urgent_notice:
            state.urgent_recommendation = safety.urgent_notice
        state.safe_recommendations = list(dict.fromkeys(state.safe_recommendations + safety.final_safety_notes))

        # 8) Final Answer Generator
        final_answer = self.runner.run_final_answer_generator(state)
        answer_payload = final_answer.final_answer
        answer_payload["disclaimer"] = safety.disclaimer
        if safety.urgent_notice:
            answer_payload["urgent_notice"] = safety.urgent_notice
        state.final_answer = answer_payload

        # 9) V7 Self-Learning: feedback при подтверждённом диагнозе
        if confirmed_diagnosis and state.history.symptoms:
            try:
                ai_diag = ""
                if state.diagnosis_probabilities:
                    ai_diag = (state.diagnosis_probabilities[0].get("disease") or "")
                elif state.differential_diagnosis:
                    first = state.differential_diagnosis[0]
                    ai_diag = first.get("disease", first.get("diagnosis", "")) if isinstance(first, dict) else ""
                if not ai_diag and state.diagnosis_candidates:
                    first = state.diagnosis_candidates[0]
                    ai_diag = first.get("name", first.get("diagnosis", "")) if isinstance(first, dict) else str(first)
                process_feedback(
                    list(state.history.symptoms),
                    ai_diag,
                    confirmed_diagnosis.strip(),
                )
                retrain_after_n_cases(100)
            except Exception:
                pass

        return state

    def run_example_scenario(self) -> dict[str, Any]:
        scenario_input = (
            "У меня слабость, головокружение и бледность. "
            "Hb 95 г/л, MCV 70 фл, ferritin 8 мкг/л."
        )
        state = self.run(user_input=scenario_input)
        return {
            "session_id": state.session_id,
            "chief_complaint": state.chief_complaint,
            "parsed_labs": [x.model_dump() for x in state.parsed_labs],
            "weighted_hypotheses": [x.model_dump() for x in state.weighted_hypotheses],
            "red_flags": state.red_flags,
            "final_answer": state.final_answer,
        }
