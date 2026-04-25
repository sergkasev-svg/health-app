from __future__ import annotations

from dataclasses import dataclass

from app.services.text_matchers import match_any


@dataclass
class TriggerExtractionResult:
    trigger_groups: list[str]
    matched_trigger_phrases: dict[str, list[str]]


class TriggerExtractor:
    """
    Detects trigger groups from routing normalization config.
    """

    def __init__(self, routing_config: dict) -> None:
        self.routing_config = routing_config

    def extract(self, normalized_text: str) -> TriggerExtractionResult:
        trigger_synonyms = self.routing_config.get("normalization", {}).get("trigger_synonyms", {})

        matched_groups: list[str] = []
        matched_phrases: dict[str, list[str]] = {}

        for group_name, values in trigger_synonyms.items():
            matched = match_any(normalized_text, values, allow_fuzzy=True, threshold=0.86)
            if matched:
                matched_groups.append(group_name)
                matched_phrases[group_name] = matched

        return TriggerExtractionResult(
            trigger_groups=matched_groups,
            matched_trigger_phrases=matched_phrases,
        )

