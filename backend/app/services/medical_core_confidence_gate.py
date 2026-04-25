from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.medical_core_confidence import decide_confidence_stop, merge_confidence_into_state


STOP_SUMMARY_HINT = (
    "Данных уже достаточно для безопасного промежуточного вывода и рекомендаций. "
    "Перехожу к структурированному резюме."
)


def run_confidence_gate(
    *,
    orchestrator_state: Optional[Dict[str, Any]],
    followup_state: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    decision = decide_confidence_stop(
        orchestrator_state=orchestrator_state,
        followup_state=followup_state,
    )
    merged_state = merge_confidence_into_state(
        orchestrator_state=dict(orchestrator_state or {}),
        followup_state=dict(followup_state or {}),
        decision=decision,
    )
    return {
        "confidence": decision.confidence,
        "should_stop": decision.should_stop,
        "should_ask_one_more": decision.should_ask_one_more,
        "next_best_slot": decision.next_best_slot,
        "reasons": decision.reasons,
        "assistant_hint": STOP_SUMMARY_HINT if decision.should_stop else None,
        "orchestrator_state": merged_state,
    }

