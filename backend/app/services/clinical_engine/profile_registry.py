"""
Единый реестр клинических профилей «За Здоровье».
Приоритет: P0 (must have) -> P1 (high value) -> P2 -> P3 (niche).
"""
from __future__ import annotations

from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.clinical_engine.profile_contract import ClinicalProfile

# Приоритеты для roadmap
P0_MUST_HAVE = 0
P1_HIGH_VALUE = 1
P2_CLINICALLY_STRONG = 2
P3_NICHE = 3

PROFILE_PRIORITY_ORDER = (P0_MUST_HAVE, P1_HIGH_VALUE, P2_CLINICALLY_STRONG, P3_NICHE)


def _build_registry() -> Dict[str, "ClinicalProfile"]:
    from app.services.clinical_engine.profiles.cbc_profile import CBCProfile
    from app.services.clinical_engine.profiles.cbc_reticulocyte_profile import CBCReticulocyteProfile
    from app.services.clinical_engine.profiles.urinalysis_profile import UrinalysisProfile
    from app.services.clinical_engine.profiles.biochemistry_profile import BiochemistryProfile
    from app.services.clinical_engine.profiles.lipid_panel_profile import LipidPanelProfile
    from app.services.clinical_engine.profiles.glucose_metabolism_profile import GlucoseMetabolismProfile
    from app.services.clinical_engine.profiles.iron_panel_profile import IronPanelProfile
    from app.services.clinical_engine.profiles.thyroid_panel_profile import ThyroidPanelProfile
    from app.services.clinical_engine.profiles.liver_panel_profile import LiverPanelProfile
    from app.services.clinical_engine.profiles.kidney_panel_profile import KidneyPanelProfile
    from app.services.clinical_engine.profiles.inflammation_panel_profile import InflammationPanelProfile
    from app.services.clinical_engine.profiles.coagulation_panel_profile import CoagulationPanelProfile
    from app.services.clinical_engine.profiles.vitamin_mineral_panel_profile import VitaminMineralPanelProfile
    from app.services.clinical_engine.profiles.b12_folate_panel_profile import B12FolatePanelProfile
    from app.services.clinical_engine.profiles.reproductive_hormones_profile import ReproductiveHormonesProfile
    from app.services.clinical_engine.profiles.adrenal_panel_profile import AdrenalPanelProfile
    from app.services.clinical_engine.profiles.organic_acids_profile import OrganicAcidsProfile
    from app.services.clinical_engine.profiles.amino_acids_panel_profile import AminoAcidsPanelProfile
    from app.services.clinical_engine.profiles.autoimmune_panel_profile import AutoimmunePanelProfile
    from app.services.clinical_engine.profiles.infectious_serology_panel_profile import InfectiousSerologyPanelProfile
    from app.services.clinical_engine.profiles.oncology_markers_panel_profile import OncologyMarkersPanelProfile
    from app.services.clinical_engine.profiles.generic_lab_profile import GenericLabProfile

    return {
        # P0 — must have
        "cbc": CBCProfile(),
        "cbc_with_reticulocytes": CBCReticulocyteProfile(),
        "urinalysis": UrinalysisProfile(),
        "biochemistry_blood": BiochemistryProfile(),
        "lipid_panel": LipidPanelProfile(),
        "glucose_metabolism": GlucoseMetabolismProfile(),
        # P1 — high value
        "iron_panel": IronPanelProfile(),
        "thyroid_panel": ThyroidPanelProfile(),
        "liver_panel": LiverPanelProfile(),
        "kidney_panel": KidneyPanelProfile(),
        "inflammation_panel": InflammationPanelProfile(),
        # P2 — clinically strong
        "coagulation_panel": CoagulationPanelProfile(),
        "vitamin_mineral_panel": VitaminMineralPanelProfile(),
        "b12_folate_panel": B12FolatePanelProfile(),
        "reproductive_hormones_panel": ReproductiveHormonesProfile(),
        "adrenal_panel": AdrenalPanelProfile(),
        # P3 — niche
        "organic_acids_urine": OrganicAcidsProfile(),
        "amino_acids_panel": AminoAcidsPanelProfile(),
        "autoimmune_panel": AutoimmunePanelProfile(),
        "infectious_serology_panel": InfectiousSerologyPanelProfile(),
        "oncology_markers_panel": OncologyMarkersPanelProfile(),
        # Fallback
        "generic_lab": GenericLabProfile(),
    }


# Ленивая инициализация, чтобы избежать циклических импортов при старте приложения
_REGISTRY: Optional[Dict[str, "ClinicalProfile"]] = None


def get_profile(profile_key: str) -> Optional["ClinicalProfile"]:
    """Вернуть профиль по ключу или None."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY.get(profile_key)


def get_all_profiles() -> Dict[str, "ClinicalProfile"]:
    """Вернуть весь реестр (для тестов и списка профилей)."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return dict(_REGISTRY)


def list_profile_keys_by_priority(max_priority: int = P3_NICHE) -> List[str]:
    """Список ключей профилей с приоритетом <= max_priority, отсортированный по приоритету."""
    registry = get_all_profiles()
    with_priority = [(k, p.priority) for k, p in registry.items()]
    with_priority.sort(key=lambda x: (x[1], x[0]))
    return [k for k, pr in with_priority if pr <= max_priority]


def get_profile_registry() -> Dict[str, "ClinicalProfile"]:
    """
    Единый реестр экземпляров профилей (то же, что get_all_profiles).
    Имя соответствует продуктовому контракту PROFILE_REGISTRY в документации.
    """
    return get_all_profiles()


# Обратная совместимость: ленивый доступ как к словарю через get_profile / get_all_profiles
__all__ = [
    "P0_MUST_HAVE",
    "P1_HIGH_VALUE",
    "P2_CLINICALLY_STRONG",
    "P3_NICHE",
    "PROFILE_PRIORITY_ORDER",
    "get_profile",
    "get_all_profiles",
    "get_profile_registry",
    "list_profile_keys_by_priority",
]
