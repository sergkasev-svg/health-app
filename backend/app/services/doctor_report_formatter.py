from __future__ import annotations

from typing import Any


class DoctorReportFormatter:
    """
    Builds a clinician-style structured text report from doctor_safe payload.
    """

    def format(self, doctor_safe: dict[str, Any]) -> str:
        if not doctor_safe:
            return ""

        zone = doctor_safe.get("zone", "")
        cluster = doctor_safe.get("cluster", "")
        trigger_groups = doctor_safe.get("trigger_groups", [])
        ranked_causes = doctor_safe.get("ranked_causes", [])
        cause_scores = doctor_safe.get("cause_scores", {})
        evidence_by_cause = doctor_safe.get("evidence_by_cause", {})
        confidence = doctor_safe.get("confidence", {})
        care_level = doctor_safe.get("care_level", {})
        recommendations = doctor_safe.get("recommendations", {})
        followup_questions = doctor_safe.get("followup_questions", [])
        memory_summary = doctor_safe.get("memory_summary", {})

        parts: list[str] = []

        parts.append(
            "Клинический разбор:\n"
            f"- zone: {zone}\n"
            f"- cluster: {cluster}\n"
            f"- triggers: {', '.join(trigger_groups) if trigger_groups else '—'}"
        )

        if ranked_causes:
            cause_lines = []
            for cause_id in ranked_causes:
                score = cause_scores.get(cause_id, 0)
                cause_lines.append(f"- {cause_id}: {score}")
            parts.append("Ранжирование причин:\n" + "\n".join(cause_lines))

        if evidence_by_cause:
            evidence_lines: list[str] = []
            for cause_id, evidence in evidence_by_cause.items():
                evidence_lines.append(f"- {cause_id}:")
                for item in evidence:
                    evidence_lines.append(f"  - {item}")
            parts.append("Поддерживающие признаки:\n" + "\n".join(evidence_lines))

        if confidence:
            parts.append(
                "Уверенность:\n"
                f"- score: {confidence.get('score')}\n"
                f"- level: {confidence.get('level')}\n"
                f"- reasons: {', '.join(confidence.get('reasons', []))}"
            )

        if care_level:
            parts.append(
                "Care level:\n"
                f"- level: {care_level.get('level')}\n"
                f"- reason: {care_level.get('reason')}\n"
                f"- action_hint: {care_level.get('action_hint')}"
            )

        if recommendations:
            rec_lines: list[str] = []
            for key in ["do_now", "avoid_now", "tests_if_recurrent", "followup_advice"]:
                items = recommendations.get(key, [])
                if items:
                    rec_lines.append(f"- {key}:")
                    rec_lines.extend(f"  - {item}" for item in items)
            if rec_lines:
                parts.append("Рекомендации:\n" + "\n".join(rec_lines))

        if followup_questions:
            parts.append("Уточняющие вопросы:\n" + "\n".join(f"- {question}" for question in followup_questions))

        if memory_summary:
            parts.append(
                "Память паттернов:\n"
                f"- events_count: {memory_summary.get('events_count')}\n"
                f"- repeated_trigger_groups: {', '.join(memory_summary.get('repeated_trigger_groups', [])) or '—'}\n"
                f"- repeated_causes: {', '.join(memory_summary.get('repeated_causes', [])) or '—'}"
            )

        return "\n\n".join(parts).strip()

