from __future__ import annotations

from app.orchestration.state_models import (
    AdaptiveQuestionOutput,
    ConsultationState,
    FinalAnswerOutput,
    LabParserOutput,
    RankingOutput,
    ReasoningOutput,
    RetrievalOutput,
    SafetyOutput,
    WeightingOutput,
)


def consultation_state_contract() -> dict:
    return ConsultationState.model_json_schema()


def adaptive_question_contract() -> dict:
    return AdaptiveQuestionOutput.model_json_schema()


def lab_parser_contract() -> dict:
    return LabParserOutput.model_json_schema()


def retrieval_contract() -> dict:
    return RetrievalOutput.model_json_schema()


def ranking_contract() -> dict:
    return RankingOutput.model_json_schema()


def reasoning_contract() -> dict:
    return ReasoningOutput.model_json_schema()


def weighting_contract() -> dict:
    return WeightingOutput.model_json_schema()


def safety_contract() -> dict:
    return SafetyOutput.model_json_schema()


def final_answer_contract() -> dict:
    return FinalAnswerOutput.model_json_schema()
