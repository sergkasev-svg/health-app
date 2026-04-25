from __future__ import annotations

from typing import Any


CONSULTATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "mode": {
            "type": "string",
            "enum": ["patient_safe", "doctor_safe", "urgent"],
        },
        "normalized_input": {"type": "string"},
        "zone": {"type": "string"},
        "cluster": {"type": "string"},
        "trigger_groups": {
            "type": "array",
            "items": {"type": "string"},
        },
        "matched_red_flags": {
            "type": "array",
            "items": {"type": "string"},
        },
        "ranked_causes": {
            "type": "array",
            "items": {"type": "string"},
        },
        "cause_scores": {
            "type": "object",
            "additionalProperties": {"type": "integer"},
        },
        "evidence_by_cause": {
            "type": "object",
            "additionalProperties": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "confidence": {
            "type": "object",
            "properties": {
                "score": {"type": "integer"},
                "level": {"type": "string"},
                "reasons": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["score", "level", "reasons"],
        },
        "recommended_tests_if_recurrent": {
            "type": "array",
            "items": {"type": "string"},
        },
        "clarifying_questions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "memory_summary": {
            "type": "object",
            "properties": {
                "events_count": {"type": "integer"},
                "repeated_trigger_groups": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "repeated_causes": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["events_count", "repeated_trigger_groups", "repeated_causes"],
        },
        "patient_text": {"type": "string"},
    },
    "required": [
        "mode",
        "normalized_input",
        "zone",
        "cluster",
        "trigger_groups",
        "matched_red_flags",
        "ranked_causes",
        "cause_scores",
        "evidence_by_cause",
        "confidence",
        "recommended_tests_if_recurrent",
        "clarifying_questions",
        "memory_summary",
        "patient_text",
    ],
}

