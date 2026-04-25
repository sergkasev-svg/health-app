from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.text_matchers import match_any


@dataclass
class GuardrailResult:
    is_urgent: bool
    matched_red_flags: list[str]
    urgent_reason: str


class MedicalGuardrails:
    """
    Separate red-flag layer.
    """

    def __init__(self, routing_config: dict[str, Any]) -> None:
        self.routing_config = routing_config

    def check(self, normalized_text: str) -> GuardrailResult:
        red_flag_rules = self.routing_config.get("red_flag_rules", {})
        match_any_rules = red_flag_rules.get("match_any", [])

        matched = match_any(normalized_text, match_any_rules, allow_fuzzy=True, threshold=0.88)

        # Higher-priority grouped interpretations
        urgent_reason = self._build_urgent_reason(normalized_text, matched)

        return GuardrailResult(
            is_urgent=bool(matched),
            matched_red_flags=matched,
            urgent_reason=urgent_reason,
        )

    @staticmethod
    def _build_urgent_reason(normalized_text: str, matched: list[str]) -> str:
        if not matched:
            return ""

        if any(x in normalized_text for x in ["боль в груди", "одышка"]):
            return "Есть симптомы, которые могут быть не только со стороны ЖКТ."
        if any(x in normalized_text for x in ["кровь в рвоте", "кровь в стуле", "черный стул", "чёрный стул"]):
            return "Есть признаки возможного кровотечения."
        if any(x in normalized_text for x in ["обморок", "спутанность", "не могу пить", "невозможно пить"]):
            return "Есть признаки системного ухудшения или обезвоживания."
        if any(x in normalized_text for x in ["сильная боль", "нарастающая боль"]):
            return "Боль звучит слишком выраженно для обычной бытовой реакции на еду."
        if "желтуха" in normalized_text:
            return "Есть признак, который требует очной оценки печени и желчевыводящей системы."
        if "температура" in normalized_text:
            return "Есть температура, что повышает вероятность острого процесса."
        return "Есть признаки, которые требуют очной оценки."

