from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CareLevelResult:
    level: str
    reason: str
    action_hint: str


class CareLevelEngine:
    """
    Care levels:
      - home
      - routine_doctor
      - urgent
      - emergency
    """

    def evaluate(
        self,
        *,
        matched_red_flags: list[str],
        ranked_causes: list[str],
        confidence_level: str,
        recurrent: bool,
    ) -> CareLevelResult:
        flags = set(matched_red_flags)

        emergency_flags = {
            "боль в груди",
            "одышка",
            "обморок",
            "кровь в рвоте",
            "кровь в стуле",
            "чёрный стул",
            "черный стул",
            "спутанность",
        }
        urgent_flags = {
            "сильная боль",
            "нарастающая боль",
            "температура",
            "неукротимая рвота",
            "желтуха",
            "не могу пить",
            "невозможно пить",
        }

        if flags.intersection(emergency_flags):
            return CareLevelResult(
                level="emergency",
                reason="Есть тревожные признаки высокого риска.",
                action_hint="Нужна срочная неотложная оценка без откладывания.",
            )

        if flags.intersection(urgent_flags):
            return CareLevelResult(
                level="urgent",
                reason="Есть признаки, которые не стоит разбирать как обычную бытовую реакцию.",
                action_hint="Нужна срочная очная оценка в ближайшее время.",
            )

        if recurrent:
            return CareLevelResult(
                level="routine_doctor",
                reason="Паттерн повторяется, значит это уже не просто случайный эпизод.",
                action_hint="Нужна плановая очная оценка и/или базовое дообследование.",
            )

        if confidence_level == "low":
            return CareLevelResult(
                level="routine_doctor",
                reason="Сигнал недостаточно чёткий для уверенного домашнего объяснения.",
                action_hint="Если это не проходит или повторится, нужна плановая очная оценка.",
            )

        if any(cause in ranked_causes for cause in ["biliary_pattern", "ulcer_or_gastritis_risk_pattern"]):
            return CareLevelResult(
                level="routine_doctor",
                reason="Есть паттерн, который лучше подтверждать при повторении или сохранении симптомов.",
                action_hint="Если жалобы сохраняются или повторяются, нужна плановая проверка.",
            )

        return CareLevelResult(
            level="home",
            reason="Похоже на бытовую постпрандиальную реакцию без красных флагов.",
            action_hint="Можно начать с домашнего наблюдения и щадящего режима.",
        )


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(x in text for x in needles)


def _collect_text(red_flags: list[Any] | None) -> str:
    parts: list[str] = []
    for item in red_flags or []:
        if isinstance(item, dict):
            msg = str(item.get("message") or item.get("title") or "").strip().lower()
            sev = str(item.get("severity") or "").strip().lower()
            if msg:
                parts.append(msg)
            if sev:
                parts.append(sev)
        else:
            s = str(item).strip().lower()
            if s:
                parts.append(s)
    return " | ".join(parts)


def normalize_runner_care_level(value: str | None) -> str:
    v = str(value or "").strip().lower()
    if v in {"urgent_clinical_assessment", "urgent", "emergency", "urgent_visit"}:
        return "urgent"
    if v in {"self_care_or_clarify", "self_care", "observe", "home_care"}:
        return "self_care"
    return "planned"


def decide_care_level(
    top_hypotheses: list[dict[str, Any]],
    red_flags: list[Any] | None,
    *,
    evidence_present: list[str] | set[str] | None = None,
    normalized_complaint: str = "",
    user_message: str = "",
) -> str:
    evidence = {str(x).strip().lower() for x in (evidence_present or []) if str(x).strip()}
    complaint = str(normalized_complaint or "").strip().lower()
    msg = str(user_message or "").strip().lower()
    red_text = _collect_text(red_flags)
    full_text = f"{msg} | {red_text}"

    top = top_hypotheses[0] if top_hypotheses else {}
    score = float(top.get("score") or 0.0)

    # absolute urgent only
    if _has_any(
        full_text,
        (
            "не хватает воздуха",
            "тяжело дышать",
            "потеря сознания",
            "сильная боль в груди",
            "отек языка",
            "отёк языка",
            "отек губ",
            "отёк губ",
            "самая сильная головная боль",
            "внезапная очень сильная головная боль",
            "кровь в моче",
            "черный стул",
            "чёрный стул",
        ),
    ):
        return "urgent_clinical_assessment"

    if {"gross_deformity", "hot_swollen_joint_with_fever", "angioedema_risk", "allergy_respiratory_risk"} & evidence:
        return "urgent_clinical_assessment"

    # stricter branch urgent gates
    if complaint == "cardio":
        if {"chest_pain", "dyspnea"} <= evidence:
            return "urgent_clinical_assessment"
        return "planned_doctor_visit"

    if complaint == "neuro":
        if "neurologic_deficit" in evidence:
            return "urgent_clinical_assessment"
        return "planned_doctor_visit"

    if complaint == "urinary":
        if {"flank_pain", "burning_urination", "fever"} <= evidence:
            return "urgent_clinical_assessment"
        return "planned_doctor_visit"

    if complaint == "oral_cavity":
        if (
            {"oral_swelling", "fever"} <= evidence
            or {"oral_pus", "fever"} <= evidence
            or {"oral_trismus_swallow", "fever"} <= evidence
        ):
            return "urgent_clinical_assessment"
        return "planned_doctor_visit"

    if complaint == "respiratory":
        if "dyspnea" in evidence:
            return "urgent_clinical_assessment"
        return "planned_doctor_visit"

    if complaint == "gastro":
        if "blood_in_stool" in evidence:
            return "urgent_clinical_assessment"
        return "planned_doctor_visit"

    if complaint == "fatigue_deficiency":
        if {"fatigue", "anemia_features", "labs_discussed"} & evidence:
            return "planned_doctor_visit"
        return "needs_clinical_clarification"

    if complaint == "pleuritic_chest_dyspnea":
        return "planned_doctor_visit"

    if complaint == "weight_loss_plateau":
        return "planned_doctor_visit"

    if complaint == "allergy_skin":
        if {"angioedema_risk", "allergy_respiratory_risk"} & evidence:
            return "urgent_clinical_assessment"
        if {"rash", "itching"} & evidence:
            return "self_care_or_clarify"
        return "needs_clinical_clarification"

    if complaint in {"orthopedics", "knee", "ankle", "shoulder", "back"}:
        if {"cannot_bear_weight", "gross_deformity"} & evidence:
            return "urgent_clinical_assessment"
        if {"swelling", "twisting_motion", "pain_on_abduction", "radicular_pain", "back_pain"} & evidence:
            return "self_care_or_clarify"
        return "needs_clinical_clarification"

    if score >= 0.80:
        return "planned_doctor_visit"
    if score >= 0.45:
        return "self_care_or_clarify"
    return "needs_clinical_clarification"
