from __future__ import annotations

from app.orchestration.state_models import AdaptiveQuestionOutput, ConsultationState


def route_after_adaptive(output: AdaptiveQuestionOutput) -> str:
    if output.red_flags_detected:
        return "urgent"
    if not output.should_stop_questioning:
        return "ask_user"
    return "continue"


def route_with_labs(state: ConsultationState) -> str:
    if state.parsed_labs:
        return "labs_flow"
    return "complaint_only_flow"
