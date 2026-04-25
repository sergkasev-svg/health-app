from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class BuiltReport:
    patient_text: str
    doctor_report: dict[str, Any]


class ReportBuilder:
    """
    Builds:
      - patient-safe report text
      - doctor-safe structured report
    """

    def build(
        self,
        *,
        normalized_input: str,
        zone: str,
        cluster: str,
        ranked_causes: list[str],
        cause_scores: dict[str, int],
        evidence_by_cause: dict[str, list[str]],
        confidence: dict[str, Any],
        care_level: dict[str, Any],
        recommendations: dict[str, Any],
        followup_questions: list[str],
        memory_summary: dict[str, Any],
    ) -> BuiltReport:
        patient_parts: list[str] = []

        if ranked_causes:
            patient_parts.append("Что вероятнее всего:\n" f"- {ranked_causes[0]}")

        if len(ranked_causes) > 1:
            patient_parts.append(
                "Какие ещё причины возможны:\n" + "\n".join(f"- {cause}" for cause in ranked_causes[1:4])
            )

        if recommendations.get("do_now"):
            patient_parts.append("Что делать сейчас:\n" + "\n".join(f"- {item}" for item in recommendations["do_now"]))

        if recommendations.get("avoid_now"):
            patient_parts.append(
                "Чего пока лучше избегать:\n" + "\n".join(f"- {item}" for item in recommendations["avoid_now"])
            )

        patient_parts.append("Какой уровень действий сейчас:\n" f"- {care_level.get('level')}: {care_level.get('action_hint')}")

        if followup_questions:
            patient_parts.append(
                "Чтобы точнее понять ситуацию:\n" + "\n".join(f"- {question}" for question in followup_questions[:3])
            )

        if recommendations.get("tests_if_recurrent"):
            patient_parts.append(
                "Если это повторяется:\n" + "\n".join(f"- {item}" for item in recommendations["tests_if_recurrent"])
            )

        doctor_report = {
            "normalized_input": normalized_input,
            "zone": zone,
            "cluster": cluster,
            "ranked_causes": ranked_causes,
            "cause_scores": cause_scores,
            "evidence_by_cause": evidence_by_cause,
            "confidence": confidence,
            "care_level": care_level,
            "recommendations": recommendations,
            "followup_questions": followup_questions,
            "memory_summary": memory_summary,
        }

        return BuiltReport(
            patient_text="\n\n".join(patient_parts).strip(),
            doctor_report=doctor_report,
        )

