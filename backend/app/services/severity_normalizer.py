from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SeverityResult:
    severity_score: int
    severity_level: str
    reasons: list[str]


class SeverityNormalizer:
    """
    Converts complaint wording into a rough severity signal.

    Scale:
      0-29   mild
      30-59  moderate
      60-100 severe
    """

    def evaluate(self, normalized_text: str) -> SeverityResult:
        score = 0
        reasons: list[str] = []

        severe_markers = [
            "сильная боль",
            "нестерпимая боль",
            "очень плохо",
            "не могу встать",
            "не могу пить",
            "многократная рвота",
            "теряю сознание",
            "обморок",
        ]
        moderate_markers = [
            "сильно тошнит",
            "сильная слабость",
            "сильно кружится голова",
            "выраженная слабость",
            "болит заметно",
            "ухудшается",
        ]
        mild_markers = [
            "слегка тошнит",
            "немного тошнит",
            "слегка болит",
            "дискомфорт",
            "тяжесть",
            "подташнивает",
        ]

        for marker in severe_markers:
            if marker in normalized_text:
                score += 25
                reasons.append(f"severe marker: {marker}")

        for marker in moderate_markers:
            if marker in normalized_text:
                score += 12
                reasons.append(f"moderate marker: {marker}")

        for marker in mild_markers:
            if marker in normalized_text:
                score += 5
                reasons.append(f"mild marker: {marker}")

        score = max(0, min(score, 100))

        if score >= 60:
            level = "severe"
        elif score >= 30:
            level = "moderate"
        else:
            level = "mild"

        return SeverityResult(
            severity_score=score,
            severity_level=level,
            reasons=reasons,
        )

