"""
Детектор симптомных маршрутов по тексту пользователя и нормализованным симптомам.
"""
from __future__ import annotations

import re
from typing import Any


def detect_symptom_routes(user_text: str, symptoms: list[str]) -> list[dict[str, Any]]:
    blob = " ".join([user_text or ""] + [str(s) for s in (symptoms or [])]).lower()
    matches: list[dict[str, Any]] = []

    def add(route_id: str, confidence: float, reason: str) -> None:
        matches.append({"route_id": route_id, "confidence": confidence, "source": "symptom", "reason": reason})

    # Emergency-ish cardio/resp (orchestrator may still override with explicit red_flags)
    if any(k in blob for k in ("боль в груди", "боль за грудин", "тяжело дышать", "одышка в покое")):
        add("respiratory_route", 0.85, "chest_pain_or_dyspnea")

    if re.search(r"\b(жжение|рези)\s+при\s+мочеиспуск", blob) or any(
        k in blob for k in ("частое мочеиспускание", "боль при мочеиспускании", "диурия")
    ):
        add("urinary_route", 0.75, "urinary_symptoms")

    has_food_context = any(
        k in blob
        for k in (
            "после еды",
            "после жирного",
            "после жареного",
            "после молочного",
            "после вина",
            "после сыра",
            "после копчен",
            "после копчён",
            "поел",
            "съел",
        )
    )
    has_food_related_gi_or_neuro = any(
        k in blob for k in ("тошнот", "головная боль", "изжог", "жжение", "кислая отрыжка", "вздут", "тяжесть")
    )
    if has_food_context and has_food_related_gi_or_neuro:
        add("food_reaction_master_route", 0.78, "food_trigger_patient_safe_master")

    has_upper_abd_context = any(
        k in blob
        for k in (
            "верхней части живота",
            "верх живота",
            "эпигастр",
            "подложеч",
            "под ребрами",
            "под рёбрами",
            "подребер",
            "подребёр",
        )
    )
    has_upper_abd_symptoms = any(
        k in blob for k in ("тошнот", "тяжесть", "изжог", "жжение", "кислая отрыжка", "горечь", "дискомфорт")
    )
    if has_upper_abd_context and has_upper_abd_symptoms:
        add("upper_abdominal_master_route", 0.8, "upper_abdominal_patient_safe_master")

    has_bowel_postmeal_context = any(
        k in blob for k in ("после еды", "после молоч", "после молока", "после фрукт", "после сладкого", "после жирного")
    )
    has_bowel_symptoms = any(
        k in blob for k in ("вздут", "урчан", "газы", "понос", "диаре", "жидкий стул", "послабление", "позывы")
    )
    if has_bowel_postmeal_context and has_bowel_symptoms:
        add("postmeal_bloating_master_route", 0.82, "postmeal_bloating_patient_safe_master")

    has_postmeal_systemic_context = any(
        k in blob for k in ("после еды", "после ужина", "после обеда", "после завтрака", "после сладк", "после десерт", "после жирн")
    )
    has_postmeal_systemic_core = any(k in blob for k in ("слабост", "дурнот", "головокруж", "сонлив", "дрож", "потлив"))
    has_postmeal_systemic_support = any(k in blob for k in ("тошнот", "головная боль", "плохо после еды"))
    has_postmeal_systemic_red = any(k in blob for k in ("обмор", "одыш", "боль в груди", "спутан", "невозможно стоять"))
    has_bowel_dominant = any(k in blob for k in ("понос", "диаре", "жидкий стул", "вздут", "газы", "урчан"))
    has_upper_abd_dominant = any(k in blob for k in ("верхней части живота", "эпигастр", "подреб"))
    if (
        has_postmeal_systemic_context
        and (has_postmeal_systemic_red or (has_postmeal_systemic_core and has_postmeal_systemic_support))
        and not has_bowel_dominant
        and not has_upper_abd_dominant
    ):
        add("postmeal_systemic_master_route", 0.81, "postmeal_systemic_patient_safe_master")

    has_postmeal_any = has_food_context or has_postmeal_systemic_context or any(
        k in blob for k in ("после молок", "после молоч", "после фастфуд", "после жарен")
    )
    has_food_symptom_any = has_food_related_gi_or_neuro or has_bowel_symptoms or has_upper_abd_symptoms
    if has_postmeal_any and has_food_symptom_any:
        add("food_symptom_super_master_route", 0.77, "food_symptom_super_master")

    if any(k in blob for k in ("боль в животе", "живот болит", "тошнот", "рвот", "диаре", "запор")):
        add("abdominal_route", 0.65, "abdominal_gi")

    if any(k in blob for k in ("сыпь", "зуд кож", "отёк квинке", "крапивниц")):
        add("allergy_route", 0.7, "allergy_skin")

    if any(k in blob for k in ("сонливость", "зябкость", "набор веса", "сердцебиен", "тремор")):
        add("endocrine_route", 0.5, "endocrine_like")

    if any(k in blob for k in ("слабость", "утомляемость", "усталость", "адинамия")):
        add("constitutional_route", 0.45, "weakness_fatigue")

    if any(k in blob for k in ("головная боль", "головокруж", "онемен", "слабость в конечност")):
        add("neuro_route", 0.55, "neuro_headache")

    # Нейро-красные флаги (маршрут нейро; emergency частично перекрывается оркестратором)
    if any(
        k in blob
        for k in (
            "нарушение речи",
            "не могу говорить",
            "перекос лица",
            "внезапная слабость руки",
            "внезапная слабость ноги",
            "потеря зрения",
            "двоится в глазах",
        )
    ):
        add("neuro_route", 0.9, "neuro_red_flags")

    if any(k in blob for k in ("температура", "озноб", "лихорадк")):
        add("respiratory_route", 0.4, "fever_infection_signal")

    matches.sort(key=lambda x: -x["confidence"])
    return matches
