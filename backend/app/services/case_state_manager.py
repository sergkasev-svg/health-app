"""Case state manager: merge extractor output into case_state (extractor → case_state)."""
from __future__ import annotations

from typing import Any


def _uniq(items: list[str]) -> list[str]:
    out = []
    seen = set()

    for item in items or []:
        v = str(item or "").strip()
        if not v:
            continue

        k = v.lower()

        if k in seen:
            continue

        seen.add(k)
        out.append(v)

    return out


def merge_extractor_output(
    case_state: dict[str, Any],
    extractor_payload: dict[str, Any],
) -> dict[str, Any]:
    case_state["chief_complaint"] = (
        extractor_payload.get("chief_complaint")
        or case_state.get("chief_complaint")
        or ""
    )

    case_state["evidence_present"] = _uniq(
        case_state.get("evidence_present", [])
        + extractor_payload.get("evidence_present", [])
    )

    case_state["evidence_absent"] = _uniq(
        case_state.get("evidence_absent", [])
        + extractor_payload.get("evidence_absent", [])
    )

    case_state["evidence_unknown"] = _uniq(
        case_state.get("evidence_unknown", [])
        + extractor_payload.get("evidence_unknown", [])
    )

    case_state["body_regions"] = _uniq(
        case_state.get("body_regions", [])
        + extractor_payload.get("body_regions", [])
    )

    case_state["temporal_markers"] = _uniq(
        case_state.get("temporal_markers", [])
        + extractor_payload.get("temporal_markers", [])
    )

    case_state["severity_hints"] = _uniq(
        case_state.get("severity_hints", [])
        + extractor_payload.get("severity_hints", [])
    )

    return case_state
