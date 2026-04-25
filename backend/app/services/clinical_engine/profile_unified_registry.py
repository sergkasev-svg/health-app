"""
Реестр P0-профилей unified pipeline (ключи для маршрутизации и будущего ClinicalProfile).

Реализации: `profiles/*_profile.py`, `p0_rules/*`, `cbc_engine`, `urinalysis_engine`.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

# Порядок приоритета внутри blood (CBC — hard override)
P0_PROFILE_KEYS: Tuple[str, ...] = (
    "cbc",
    "cbc_reticulocytes",
    "lipid_panel",
    "biochemistry_basic",
    "glucose_metabolism",
    "urinalysis",
    "organic_acids_urine",
)

PROFILE_TO_MATERIAL: Dict[str, str] = {
    "cbc": "blood",
    "cbc_reticulocytes": "blood",
    "lipid_panel": "blood",
    "biochemistry_basic": "blood",
    "glucose_metabolism": "blood",
    "urinalysis": "urine",
    "organic_acids_urine": "urine",
}


def allowed_profiles_for_material(material: str) -> List[str]:
    return [p for p, m in PROFILE_TO_MATERIAL.items() if m == material]
