"""
Реестр биоматериалов и допустимых профилей (справочник для методички и аудита).

CORE: blood, urine, stool — основная нагрузка продукта.
IMPORTANT: saliva, swab, semen, csf.
ADVANCED: tissue (гистология), serology, genetics.
"""
from __future__ import annotations

from typing import Dict, List

# material_kind -> список логических профилей (строки — ключи маршрутизации / будущие движки)
MATERIAL_ALLOWED_PROFILES: Dict[str, List[str]] = {
    "blood": [
        "cbc",
        "cbc_with_reticulocytes",
        "lipid_panel",
        "biochemistry",
        "liver_panel",
        "glucose_metabolism",
        "thyroid",
        "vitamin_panel",
        "coagulation",
        "hormones",
        "inflammation",
        "iron_panel",
    ],
    "urine": [
        "urinalysis",
        "organic_acids_urine",
        "microalbumin_urine",
        "urine_24h",
    ],
    "stool": [
        "coprogram",
        "occult_blood",
        "parasites",
        "microbiota",
    ],
    "saliva": [
        "cortisol_saliva",
        "hormone_saliva",
        "dna_saliva",
    ],
    "swab": [
        "pcr_urogenital",
        "pcr_ent",
        "microbiology_swab",
    ],
    "semen": ["spermogram"],
    "csf": ["csf_analysis"],
    "tissue": ["histology"],
    "serology": ["infectious_serology", "autoimmune_serology"],
    "genetics": ["ngs_panel", "carrier_screening"],
}

MATERIAL_FORBIDDEN_CROSS: Dict[str, List[str]] = {
    "blood": ["urinalysis", "stool_coprogram"],
    "urine": ["cbc", "lipid_panel", "biochemistry_blood"],
    "stool": ["cbc", "urinalysis", "lipid_panel"],
}
