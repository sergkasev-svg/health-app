from __future__ import annotations

from typing import Any

from .repository import MedicalCoreRepository


class MedicalCoreEngine:
    """Optional read-only helper around the new medical_core bundle.

    Add-only: does not replace current consultation pipeline.
    """

    def __init__(self, repo: MedicalCoreRepository | None = None) -> None:
        self.repo = repo or MedicalCoreRepository()

    def find_best_entries(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return self.repo.search(query, limit=limit)

    def complaint_plan(self, complaint_entry_id: str) -> dict[str, Any]:
        row = self.repo.get(complaint_entry_id) or {}
        links = self.repo.complaint_links().get(complaint_entry_id) or {}
        return {
            "entry": row,
            "candidate_diseases": links.get("candidate_diseases") or [],
            "behavior_rules": self.repo.behavior_rules().get("default_dialogue_meta") or {},
        }

    def first_question(self, entry_id: str) -> str:
        row = self.repo.get(entry_id) or {}
        fu = row.get("follow_up") or {}
        red = list(fu.get("red_flag_questions") or [])
        if red:
            return str(red[0])
        must_ask = list(fu.get("must_ask") or [])
        return str(must_ask[0]) if must_ask else "Когда начались симптомы?"

    def safe_summary(self, entry_id: str) -> dict[str, Any]:
        row = self.repo.get(entry_id) or {}
        return {
            "entry_id": row.get("entry_id"),
            "name": row.get("name"),
            "type": row.get("type"),
            "care_level": ((row.get("triage") or {}).get("recommended_care_level") or "planned_consult"),
            "red_flags": ((row.get("triage") or {}).get("red_flags") or [])[:5],
            "first_line": ((row.get("care") or {}).get("first_line") or [])[:5],
            "tests": ((row.get("care") or {}).get("tests") or [])[:3],
            "nutrition": ((row.get("care") or {}).get("nutrition") or [])[:3],
            "activity": ((row.get("care") or {}).get("activity") or [])[:3],
            "disclaimer": ((row.get("policy") or {}).get("disclaimer_short") or ""),
        }
