from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass
class TimelineResult:
    onset_timing: str
    duration_hint: str
    timeline_clues: list[str]


class TimelineExtractor:
    """
    Extracts rough timing:
    - immediate
    - early_postprandial
    - delayed
    - persistent
    - unknown
    """

    def extract(self, normalized_text: str) -> TimelineResult:
        timeline_clues: list[str] = []

        immediate_patterns = [
            "сразу после еды",
            "сразу после",
            "прямо после еды",
            "через несколько минут",
            "через 5 минут",
            "через 10 минут",
        ]
        early_patterns = [
            "через полчаса",
            "через 30 минут",
            "через час",
            "через 1 час",
            "после еды",
        ]
        delayed_patterns = [
            "через несколько часов",
            "через 2 часа",
            "через 3 часа",
            "к вечеру",
            "ночью после еды",
        ]
        persistent_patterns = [
            "весь день",
            "не проходит",
            "уже второй день",
            "уже 2 дня",
            "уже 3 дня",
            "постоянно",
        ]

        onset_timing = "unknown"
        duration_hint = "unknown"

        if self._has_any(normalized_text, immediate_patterns):
            onset_timing = "immediate"
            timeline_clues.append("immediate onset")
        elif self._has_any(normalized_text, early_patterns):
            onset_timing = "early_postprandial"
            timeline_clues.append("early postprandial onset")
        elif self._has_any(normalized_text, delayed_patterns):
            onset_timing = "delayed"
            timeline_clues.append("delayed onset")

        if self._has_any(normalized_text, persistent_patterns):
            duration_hint = "persistent"
            timeline_clues.append("persistent duration")
        else:
            match = re.search(r"уже\s+(\d+)\s+(час|часа|часов|день|дня|дней)", normalized_text)
            if match:
                duration_hint = f"reported_duration_{match.group(1)}_{match.group(2)}"
                timeline_clues.append(f"duration: {match.group(0)}")

        return TimelineResult(
            onset_timing=onset_timing,
            duration_hint=duration_hint,
            timeline_clues=timeline_clues,
        )

    @staticmethod
    def _has_any(text: str, phrases: list[str]) -> bool:
        return any(phrase in text for phrase in phrases)

