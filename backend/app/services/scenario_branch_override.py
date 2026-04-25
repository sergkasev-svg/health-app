from __future__ import annotations

from typing import Any


SCENARIO_TO_BRANCH = {
    "respiratory_mild_uri": ("respiratory", ["respiratory"]),
    "urinary_flank_pain_fever": ("urinary", ["urinary"]),
    "urinary_cystitis": ("urinary", ["urinary"]),
    "cardio_chest_pain_exertion": ("cardio", ["cardio"]),
    "cardio_hypertension": ("cardio", ["cardio"]),
    "oral_dental_abscess": ("oral_cavity", ["oral_cavity"]),
    "oral_wisdom_tooth": ("oral_cavity", ["oral_cavity"]),
    "neuro_migraine": ("neuro", ["neuro"]),
    "fatigue_deficiency_pattern": ("fatigue_deficiency", ["fatigue_deficiency"]),
    "gastro_gastroenteritis": ("gastro", ["gastro"]),
    "allergy_skin_reaction": ("allergy_skin", ["allergy_skin"]),
}


def apply_scenario_branch_override(case_state: dict[str, Any]) -> dict[str, Any]:
    scenario_id = str(
        case_state.get("primary_scenario_id")
        or case_state.get("scenario_id")
        or case_state.get("scenario_name")
        or ""
    ).strip()

    if not scenario_id:
        return case_state

    if scenario_id in SCENARIO_TO_BRANCH:
        branch, body_regions = SCENARIO_TO_BRANCH[scenario_id]
        case_state["primary_scope"] = branch
        case_state["body_regions"] = body_regions
        case_state["branch"] = branch
        case_state["normalized_complaint"] = branch

    return case_state
