from __future__ import annotations

from typing import Any


def make_reasoning_debug_payload(
    *,
    normalized: str,
    zone: str,
    cluster: str,
    trigger_groups: list[str],
    matched_red_flags: list[str],
    matched_symptoms: list[str] | None = None,
    zone_scores: dict[str, int] | None = None,
    cluster_scores: dict[str, int] | None = None,
    cause_scores: dict[str, int] | None = None,
    ranked_causes: list[str],
    evidence_map: dict[str, list[str]] | None = None,
    recurrent: bool,
    template: str,
    recommended_tests: list[str],
    clarifying_questions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "normalized": normalized,
        "matched_symptoms": matched_symptoms or [],
        "zone_scores": zone_scores or {},
        "zone": zone,
        "cluster_scores": cluster_scores or {},
        "cluster": cluster,
        "trigger_groups": trigger_groups,
        "matched_red_flags": matched_red_flags,
        "cause_scores": cause_scores or {},
        "ranked_causes": ranked_causes,
        "evidence_map": evidence_map or {},
        "recurrent": recurrent,
        "template": template,
        "recommended_tests": recommended_tests,
        "clarifying_questions": clarifying_questions or [],
    }


def print_reasoning_debug(payload: dict[str, Any]) -> None:
    print("=== FOOD ROUTER V4 DEBUG ===")
    for key, value in payload.items():
        print(f"{key}: {value}")
    print("============================")

