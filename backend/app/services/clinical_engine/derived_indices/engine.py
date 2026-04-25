"""
Единая точка входа: виталы + ОАК + тиреоидный текст из документа.
Не изменяет profile rules / interpret_cbc — только добавляет расчётный слой поверх извлечённых данных.
"""
from __future__ import annotations

from typing import List

from app.services.lab_value_extractor import LabValue

from app.services.clinical_engine.derived_indices.autonomic_indices import compute_kerdo_index
from app.services.clinical_engine.derived_indices.body_indices import compute_bmi
from app.services.clinical_engine.derived_indices.cbc_indices import compute_cbc_derived_indices
from app.services.clinical_engine.derived_indices.contract import DerivedIndex
from app.services.clinical_engine.derived_indices.registry import sort_derived_indices
from app.services.clinical_engine.derived_indices.thyroid_indices import compute_iti
from app.services.clinical_engine.derived_indices.vitals import extract_vitals_from_text


def compute_derived_indices_for_document(
    extracted_text: str,
    lab_values: List[LabValue],
) -> List[DerivedIndex]:
    """
    Считает все поддерживаемые индексы по полному тексту документа и списку LabValue (ОАК).

    Порядок: ИМТ, Кердо, ИТИ, затем индексы по ОАК (NLR, SII, SIRI, AISI, Гаркави, ИИР).
    """
    text = extracted_text or ""
    vitals = extract_vitals_from_text(text)
    out: List[DerivedIndex] = []

    bmi = compute_bmi(vitals)
    if bmi is not None:
        out.append(bmi)

    kerdo = compute_kerdo_index(vitals)
    if kerdo is not None:
        out.append(kerdo)

    out.append(compute_iti(text))
    out.extend(compute_cbc_derived_indices(lab_values))

    return sort_derived_indices(out)


def format_derived_indices_section(
    indices: List[DerivedIndex],
    *,
    for_patient: bool = False,
    include_exploratory_for_patient: bool = False,
) -> str:
    """
    Текстовый блок для отчёта. Для пациента по умолчанию только patient_visible
    и без exploratory (Гаркави, ИИР, Кердо) — чтобы не плодить тревогу.
    """
    title = "Интегральные и расчётные индексы"
    lines: List[str] = [title, ""]
    for di in indices:
        if for_patient:
            if not di.patient_visible:
                continue
            if di.confidence == "exploratory" and not include_exploratory_for_patient:
                continue
        elif not di.physician_visible:
            continue
        lines.append(di.to_report_line())
    if len(lines) <= 2:
        return ""
    return "\n".join(lines)
