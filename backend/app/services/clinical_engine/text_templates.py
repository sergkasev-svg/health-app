"""
Заголовки и подзаголовки отчёта строго по document_type и profile.
Никаких дефолтных «органические кислоты» для всех документов.
"""
from __future__ import annotations

from typing import Tuple

_TITLE_MAP = {
    "biochemistry_blood": "Структурированная интерпретация биохимического анализа крови",
    "lipid_panel": "Структурированная интерпретация биохимического анализа крови",
    "cbc": "Структурированная интерпретация общеклинического анализа крови с лейкоцитарной формулой",
    "cbc_with_reticulocytes": "Структурированная интерпретация общеклинического анализа крови с лейкоцитарной формулой и ретикулоцитами",
    "thyroid_panel": "Структурированная интерпретация гормонов щитовидной железы",
    "urinalysis": "Структурированная интерпретация общего анализа мочи",
    "organic_acids_urine": "Структурированная интерпретация органических кислот в моче",
    "generic_lab_document": "Интерпретация лабораторного документа",
}

_SUBTITLE_MAP = {
    "lipid_panel": "Структурированная интерпретация биохимического анализа крови",
    "biochemistry_blood": "Структурированная интерпретация биохимического анализа крови",
    "cbc": "Общеклинический анализ крови с лейкоцитарной формулой",
    "cbc_with_reticulocytes": "ОАК с лейкоформулой и ретикулоцитами",
    "generic_lab_document": "Общий лабораторный результат",
}


def get_report_title_subtitle(document_type: str, profile: str) -> Tuple[str, str]:
    """Title и subtitle только из document_type/profile; без fallback на organic acids."""
    title = _TITLE_MAP.get(document_type) or _TITLE_MAP.get(profile) or "Отчёт по лабораторному документу"
    subtitle = _SUBTITLE_MAP.get(profile) or _SUBTITLE_MAP.get(document_type) or ""
    return title, subtitle
