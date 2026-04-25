"""
Реестр лабораторных профилей. Роутер не завязан на один тип — generic_lab_document только крайний fallback.
"""
from typing import List

# Порядок приоритета при определении типа документа (organic_acids и lipid проверяются раньше в document_physician_report)
PROFILE_TYPES: List[str] = [
    "organic_acids",
    "lipid_panel",
    "cbc",
    "cbc_with_reticulocytes",
    "biochemistry",
    "liver_panel",
    "thyroid_panel",
    "vitamin_panel",
    "urinalysis",
    "generic_lab_document",
]

# Типы, для которых есть полноценный интерпретатор (не generic)
INTERPRETED_PROFILES = frozenset({
    "organic_acids",
    "lipid_panel",
    "cbc",
    "cbc_with_reticulocytes",
})
