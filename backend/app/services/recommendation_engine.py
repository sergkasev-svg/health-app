from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RecommendationResult:
    do_now: list[str]
    avoid_now: list[str]
    tests_if_recurrent: list[str]
    followup_advice: list[str]


class RecommendationEngine:
    """
    Builds practical recommendations from ranked causes and care level.
    """

    def build(
        self,
        *,
        ranked_causes: list[str],
        care_level: str,
        recurrent: bool,
        recommended_tests: list[str],
    ) -> RecommendationResult:
        do_now: list[str] = [
            "пить воду маленькими порциями",
            "не перегружать ЖКТ тяжёлой едой",
        ]
        avoid_now: list[str] = []
        followup_advice: list[str] = []

        cause_set = set(ranked_causes)

        if "reflux_pattern" in cause_set:
            do_now.extend(
                [
                    "не ложиться сразу после еды",
                    "есть меньшими порциями",
                ]
            )
            avoid_now.extend(
                [
                    "поздний ужин",
                    "обильную жирную еду",
                ]
            )

        if "fatty_food_overload" in cause_set or "fatty_food_systemic_overload" in cause_set:
            do_now.append("дать организму время восстановиться без жирной еды несколько часов")
            avoid_now.extend(
                [
                    "жирное",
                    "жареное",
                    "переедание",
                ]
            )

        if "biliary_pattern" in cause_set:
            do_now.append("наблюдать, не усиливается ли дискомфорт справа под рёбрами")
            avoid_now.extend(
                [
                    "жирную пищу",
                    "очень тяжёлую еду",
                ]
            )

        if "dairy_lactose_pattern" in cause_set:
            do_now.append("отметить связь симптомов именно с молочным")
            avoid_now.append("молочные продукты до уточнения триггера")

        if "fodmap_fermentation_pattern" in cause_set:
            do_now.append("отметить связь с продуктами вроде лука, чеснока, бобовых, соков")
            avoid_now.extend(
                [
                    "продукты-триггеры",
                    "большие объёмы тяжёлой еды",
                ]
            )

        if "sugar_glucose_pattern" in cause_set:
            do_now.append("наблюдать, нет ли повторяемости именно после сладкого")
            avoid_now.extend(
                [
                    "много сладкого за раз",
                    "сладкое после тяжёлой еды",
                ]
            )

        if care_level == "home":
            followup_advice.append("если симптомы уменьшаются — достаточно наблюдения")
        elif care_level == "routine_doctor":
            followup_advice.append("если это повторяется — стоит перейти к плановой проверке")
        elif care_level in {"urgent", "emergency"}:
            followup_advice.append("не затягивать с очной оценкой")

        if recurrent and recommended_tests:
            followup_advice.append("при повторении можно обсудить базовое обследование")
        tests_if_recurrent = list(dict.fromkeys(recommended_tests))

        return RecommendationResult(
            do_now=list(dict.fromkeys(do_now)),
            avoid_now=list(dict.fromkeys(avoid_now)),
            tests_if_recurrent=tests_if_recurrent,
            followup_advice=list(dict.fromkeys(followup_advice)),
        )


def build_recommendations(
    care_level: str,
    top_hypotheses: list[dict[str, Any]],
    ranked_state: dict[str, Any],
) -> dict[str, list[str]]:
    self_care = [str(x).strip() for x in (ranked_state.get("safe_actions") or []) if str(x).strip()]
    tests = [str(x).strip() for x in (ranked_state.get("suggested_tests") or []) if str(x).strip()]
    if care_level == "urgent_clinical_assessment":
        self_care = [
            "Не нагружайте ногу.",
            "Холод через ткань на 15-20 минут.",
            "Держите ногу немного выше уровня сердца.",
        ]
    if not self_care:
        self_care = ["Щадящий режим и наблюдение динамики."]
    if not tests and top_hypotheses:
        tests = ["Очный осмотр травматолога по показаниям."]
    return {"self_care": self_care[:4], "tests": tests[:4]}

