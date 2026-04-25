from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CarePlan:
    what_to_do: list[str]
    what_to_avoid: list[str]
    when_to_seek_help: list[str]
    tests_to_consider_if_recurrent: list[str]


class CarePlanGenerator:
    """
    Converts router output into a clearer action plan.
    """

    def generate(self, result: dict[str, Any]) -> CarePlan:
        doctor_safe = result.get("doctor_safe", {}) or {}
        recommendations = doctor_safe.get("recommendations", {}) or {}

        what_to_do = list(recommendations.get("do_now", []))
        what_to_avoid = list(recommendations.get("avoid_now", []))
        tests = list(recommendations.get("tests_if_recurrent", []))

        care_level = result.get("care_level") or doctor_safe.get("care_level", {}).get("level", "")
        when_to_seek_help = self._help_rules(care_level)

        return CarePlan(
            what_to_do=list(dict.fromkeys(what_to_do)),
            what_to_avoid=list(dict.fromkeys(what_to_avoid)),
            when_to_seek_help=list(dict.fromkeys(when_to_seek_help)),
            tests_to_consider_if_recurrent=list(dict.fromkeys(tests)),
        )

    @staticmethod
    def _help_rules(care_level: str) -> list[str]:
        if care_level == "home":
            return [
                "если симптомы не уменьшаются",
                "если становится хуже",
                "если эпизоды повторяются",
            ]
        if care_level == "routine_doctor":
            return [
                "если жалобы повторяются",
                "если сохраняются несколько дней",
                "если нужен плановый разбор причин",
            ]
        if care_level == "urgent":
            return [
                "обратиться за срочной очной оценкой",
            ]
        if care_level == "emergency":
            return [
                "обратиться за неотложной помощью без откладывания",
            ]
        return [
            "если состояние ухудшается",
        ]

