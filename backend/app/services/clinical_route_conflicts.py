"""
Правила конфликтов маршрутов: что блокируется при доминирующем document/lab route.
"""
from __future__ import annotations

from typing import Iterable


def apply_route_conflicts(
    primary_document_route: str | None,
    symptom_routes: Iterable[str],
    has_strong_urinary_symptoms: bool,
) -> tuple[list[str], list[str]]:
    """
    Возвращает (blocked_routes, reasons).
    has_strong_urinary_symptoms — дизурия и т.п. для снятия блока urinary при OA.
    """
    blocked: list[str] = []
    reasons: list[str] = []
    sym_set = set(symptom_routes or [])

    if primary_document_route == "organic_acids_route":
        blocked.extend(
            [
                "urinary_route",
                "allergy_route",
                "lipid_route",
                "urine_general_route",
            ]
        )
        reasons.append(
            "organic_acids: block urinary/allergy/lipid/histamine-like domains without symptom support"
        )
        if not has_strong_urinary_symptoms:
            reasons.append("urinary_route blocked without dysuria/frequency evidence")
        else:
            blocked = [b for b in blocked if b != "urinary_route"]
            reasons.append("urinary_route allowed: symptom support")

    if primary_document_route == "cbc_route":
        for r in ("lipid_route", "organic_acids_route", "thyroid_route"):
            if r not in sym_set:
                blocked.append(r)
        reasons.append("cbc document: block cross-domain lab routes without dual document")

    if primary_document_route == "thyroid_route":
        if "urinary_route" not in sym_set:
            blocked.extend(["urinary_route", "urine_general_route"])
        reasons.append("thyroid document: block urinary without symptoms")

    if primary_document_route == "urine_general_route":
        blocked.append("organic_acids_route")
        reasons.append("urine general OAС: not organic acids panel")

    if primary_document_route == "lipid_route":
        blocked.append("iron_route")
        reasons.append("lipid: iron route deprioritized without iron document")

    return list(dict.fromkeys(blocked)), reasons
