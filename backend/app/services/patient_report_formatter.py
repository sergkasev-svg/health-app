from __future__ import annotations

from typing import Any


class PatientReportFormatter:
    """
    Builds a clean, user-facing report from the v6 output package.
    """

    def format(self, result: dict[str, Any]) -> str:
        mode = result.get("mode", "patient_safe")
        text = str(result.get("text", "")).strip()
        care_level = str(result.get("care_level", "")).strip()
        doctor_safe = result.get("doctor_safe", {}) or {}

        if mode == "urgent":
            return text

        sections: list[str] = []

        if text:
            sections.append(text)

        if care_level:
            care_label = self._care_level_label(care_level)
            sections.append(f"Уровень действий сейчас:\n- {care_label}")

        confidence = doctor_safe.get("confidence", {})
        confidence_level = confidence.get("level")
        if confidence_level:
            sections.append(
                "Насколько уверенно это похоже на данный паттерн:\n"
                f"- {self._confidence_label(str(confidence_level))}"
            )

        memory_summary = doctor_safe.get("memory_summary", {})
        repeated_trigger_groups = memory_summary.get("repeated_trigger_groups", [])
        if repeated_trigger_groups:
            sections.append(
                "Что уже выглядит повторяющимся:\n" + "\n".join(f"- {item}" for item in repeated_trigger_groups)
            )

        return "\n\n".join(section.strip() for section in sections if section).strip()

    @staticmethod
    def _care_level_label(level: str) -> str:
        mapping = {
            "home": "домашнее наблюдение",
            "routine_doctor": "плановая очная оценка",
            "urgent": "срочная очная оценка",
            "emergency": "неотложная помощь",
        }
        return mapping.get(level, level)

    @staticmethod
    def _confidence_label(level: str) -> str:
        mapping = {
            "low": "низкая уверенность, полезны уточнения",
            "medium": "средняя уверенность",
            "high": "высокая уверенность по текущим данным",
        }
        return mapping.get(level, level)

