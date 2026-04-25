from __future__ import annotations

from typing import Any

BRANCH_HINTS = {
    "orthopedics": {"knee", "ankle", "back", "shoulder", "neck", "joint", "trauma"},
    "oral_cavity": {"tooth", "gum", "oral", "mouth", "tongue", "jaw", "dental"},
    "respiratory": {"cough", "throat", "fever", "respiratory", "breath"},
    "gastro": {"abdomen", "stomach", "vomit", "diarrhea", "nausea"},
    "cardio": {"chest", "palpitations", "pressure", "heart"},
    "neuro": {"headache", "weakness", "numbness", "dizzy"},
    "urinary": {"urinary", "flank", "dysuria", "kidney"},
}


def _infer_branch(hypothesis_id: str) -> str:
    hid = (hypothesis_id or "").lower()
    for branch, markers in BRANCH_HINTS.items():
        if any(marker in hid for marker in markers):
            return branch
    return ""


def check(case_state: dict[str, Any], ranked: list[dict[str, Any]]) -> dict[str, Any]:
    """Проверка смены топ-гипотезы и ветки (reasoning core)."""
    previous_top = ""
    previous_branch = ""
    current_top = ""
    current_branch = ""

    previous = case_state.get("top_hypotheses") or []
    if previous:
        previous_top = str(previous[0].get("id", ""))
        previous_branch = _infer_branch(previous_top)

    if ranked:
        current_top = str(ranked[0].get("id", ""))
        current_branch = _infer_branch(current_top)

    changed = bool(previous_top and current_top and previous_top != current_top)
    branch_changed = bool(previous_branch and current_branch and previous_branch != current_branch)

    reasons: list[str] = []
    if changed:
        reasons.append("top_hypothesis_changed")
    if branch_changed:
        reasons.append("branch_changed")

    return {
        "previous_top": previous_top,
        "current_top": current_top,
        "previous_branch": previous_branch,
        "current_branch": current_branch,
        "changed": changed,
        "branch_changed": branch_changed,
        "reason": ",".join(reasons),
    }


def detect_contradictions(evidence_present: list[str], evidence_absent: list[str]) -> list[str]:
    present = set(evidence_present or [])
    absent = set(evidence_absent or [])
    out: list[str] = []
    pairs = [
        ("knee_trauma", "no_trauma_history", "Есть и травма, и отрицание травмы — нужно уточнить механизм."),
        ("cannot_bear_weight", "cannot_bear_weight", "Одновременно указано и наличие, и отсутствие невозможности опоры."),
        ("swelling", "swelling", "Одновременно указано и наличие, и отсутствие отека."),
    ]
    for p, a, msg in pairs:
        if p in present and a in absent:
            out.append(msg)
    return out

