from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FollowupSelectionResult:
    should_ask: bool
    questions: list[str]
    reason: str


class FollowupSelector:
    """
    Selects 1-3 follow-up questions based on missing evidence and ambiguity.
    """

    def select(
        self,
        *,
        zone: str,
        cluster: str,
        ranked_causes: list[str],
        evidence_map: dict[str, list[str]],
        confidence_level: str,
        recurrent: bool,
        matched_red_flags: list[str],
    ) -> FollowupSelectionResult:
        _ = cluster
        _ = evidence_map

        if matched_red_flags:
            return FollowupSelectionResult(False, [], "urgent case")

        if confidence_level == "high":
            return FollowupSelectionResult(False, [], "enough confidence")

        if not ranked_causes:
            return FollowupSelectionResult(
                True,
                self._generic_questions(recurrent),
                "no strong cause ranking",
            )

        top = ranked_causes[:2]

        if zone == "upper_gi_zone":
            return FollowupSelectionResult(
                True,
                self._upper_gi_questions(top, recurrent),
                "upper GI ambiguity",
            )

        if zone == "right_upper_abdominal_zone":
            return FollowupSelectionResult(
                True,
                self._ruq_questions(top, recurrent),
                "RUQ ambiguity",
            )

        if zone == "bowel_zone":
            return FollowupSelectionResult(
                True,
                self._bowel_questions(top, recurrent),
                "bowel ambiguity",
            )

        if zone == "systemic_zone":
            return FollowupSelectionResult(
                True,
                self._systemic_questions(top, recurrent),
                "systemic ambiguity",
            )

        return FollowupSelectionResult(
            True,
            self._generic_questions(recurrent),
            "fallback questions",
        )

    @staticmethod
    def _generic_questions(recurrent: bool) -> list[str]:
        base = [
            "Где именно основной дискомфорт: верх живота, справа под рёбрами, кишечник или просто слабость?",
            "Какая еда была триггером: жирное, молочное, сладкое, алкоголь или что-то ещё?",
        ]
        if recurrent:
            base.append("Это повторяется после одинаковых продуктов или было впервые?")
        else:
            base.append("Это было один раз или уже бывало раньше?")
        return base[:3]

    @staticmethod
    def _upper_gi_questions(top: list[str], recurrent: bool) -> list[str]:
        questions = [
            "Это больше тяжесть после еды или именно боль?",
            "Есть ли жжение, кислый привкус или хуже, когда ложитесь?",
        ]
        if "biliary_pattern" in top:
            questions.append("Есть ли горечь во рту или дискомфорт справа под рёбрами?")
        elif recurrent:
            questions.append("Такое повторяется после жирной или тяжёлой еды?")
        else:
            questions.append("Было ли переедание или очень тяжёлая еда?")
        return questions[:3]

    @staticmethod
    def _ruq_questions(top: list[str], recurrent: bool) -> list[str]:
        _ = top
        questions = [
            "Дискомфорт именно справа под рёбрами или по центру живота?",
            "Есть ли горечь во рту, рвота или отдаёт ли боль в спину?",
        ]
        if recurrent:
            questions.append("Такое бывает именно после жирной еды?")
        else:
            questions.append("Это началось сразу после жирной еды или позже?")
        return questions[:3]

    @staticmethod
    def _bowel_questions(top: list[str], recurrent: bool) -> list[str]:
        _ = top
        questions = [
            "Было ли это после молочного, сладкого или продуктов вроде лука, чеснока, бобовых?",
            "Есть ли только вздутие и урчание или ещё и жидкий стул?",
        ]
        if recurrent:
            questions.append("Это повторяется и связано ли это с изменением стула?")
        else:
            questions.append("Это был разовый эпизод или уже бывало раньше?")
        return questions[:3]

    @staticmethod
    def _systemic_questions(top: list[str], recurrent: bool) -> list[str]:
        _ = top
        questions = [
            "Это было после жирной еды, сладкого или алкоголя?",
            "Есть ли потливость, дрожь, выраженная сонливость или просто тошнота с головной болью?",
        ]
        if recurrent:
            questions.append("Такое повторяется после одних и тех же продуктов?")
        else:
            questions.append("Это случилось впервые или уже бывало?")
        return questions[:3]

