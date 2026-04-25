"""
Роутинг профиля интерпретации по document_type и извлечённым значениям.
Profile определяет, какие clinical rules применять.
"""
from __future__ import annotations

from typing import List, Optional

from app.services.clinical_engine.contracts import DocumentType, LabValue


def get_profile(document_type: DocumentType, values: List[LabValue]) -> str:
    """
    По типу документа и списку значений возвращает профиль интерпретации.
    biochemistry_blood + наличие липидных маркеров → lipid_panel.
    """
    codes = {v.code for v in values}
    lipid_codes = {"total_cholesterol", "ldl_cholesterol", "hdl_cholesterol", "triglycerides"}

    if document_type == DocumentType.BIOCHEMISTRY_BLOOD:
        if codes & lipid_codes:
            return "lipid_panel"
        return "biochemistry_blood"

    if document_type == DocumentType.LIPID_PANEL:
        return "lipid_panel"

    if document_type == DocumentType.CBC:
        return "cbc"
    if document_type == DocumentType.CBC_RETIC:
        return "cbc_reticulocytes"

    if document_type == DocumentType.THYROID_PANEL:
        return "thyroid_panel"
    if document_type == DocumentType.URINALYSIS:
        return "urinalysis"
    if document_type == DocumentType.ORGANIC_ACIDS_URINE:
        return "organic_acids_urine"

    return "generic_lab"


def route_profile(document_type: str, values_by_code: dict) -> str:
    """
    Спека: route_profile(document_type, values) → profile.
    values — dict[str, LabValue] или dict с ключами-кодами маркеров.
    """
    if document_type == "biochemistry_blood":
        lipid_codes = {"total_cholesterol", "ldl_cholesterol", "hdl_cholesterol", "triglycerides"}
        if values_by_code and (set(values_by_code) & lipid_codes):
            return "lipid_panel"
        return "biochemistry_blood"
    if document_type == "lipid_panel":
        return "lipid_panel"
    return document_type or "generic_lab"
