"""
Каталог клинических профилей «За Здоровье»: приоритет (P0–P3), этап внедрения, краткое описание.
Используется для roadmap, UI и проверки согласованности с PROFILE_REGISTRY.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Tuple


@dataclass(frozen=True)
class ProfileCatalogEntry:
    """Метаданные одного профиля (без импорта классов профилей)."""

    key: str
    priority: int  # 0=P0, 1=P1, 2=P2, 3=P3
    phase: int  # этап roadmap: 1 = ядро 70–80%, 2 = high value, 3 = expansions, 4 = niche
    title_ru: str
    markers_summary: str


# Приоритеты совпадают с profile_registry.P0_MUST_HAVE и т.д.
P0, P1, P2, P3 = 0, 1, 2, 3

PROFILE_CATALOG: Dict[str, ProfileCatalogEntry] = {
    # --- P0 must have (этап 1) ---
    "cbc": ProfileCatalogEntry("cbc", P0, 1, "ОАК (общий анализ крови)", "Hb, RBC, Hct, индексы, WBC+форма, PLT, СОЭ"),
    "cbc_with_reticulocytes": ProfileCatalogEntry(
        "cbc_with_reticulocytes", P0, 1, "ОАК с ретикулоцитами", "ОАК + ретикулоциты",
    ),
    "urinalysis": ProfileCatalogEntry("urinalysis", P0, 1, "ОАМ (общий анализ мочи)", "pH, плотность, белок, глюкоза, нитриты, осадок, кровь"),
    "biochemistry_blood": ProfileCatalogEntry(
        "biochemistry_blood", P0, 1, "Биохимия крови (базовая)", "АЛТ, АСТ, билирубин, креатинин, мочевина, белок, глюкоза, мочевая кислота",
    ),
    "lipid_panel": ProfileCatalogEntry(
        "lipid_panel", P0, 1, "Липидный профиль", "ОХС, ЛПНП, ЛПВП, ТГ, non-HDL, ApoB/ApoA1, Lp(a)",
    ),
    "glucose_metabolism": ProfileCatalogEntry(
        "glucose_metabolism", P0, 1, "Углеводный обмен", "Глюкоза, HbA1c, фруктозамин, инсулин, HOMA-IR",
    ),
    # --- P1 high value (этап 2) ---
    "iron_panel": ProfileCatalogEntry(
        "iron_panel", P1, 2, "Железный обмен", "Ферритин, Fe, трансферрин, ОЖСС/ЛЖСС, насыщение",
    ),
    "thyroid_panel": ProfileCatalogEntry(
        "thyroid_panel", P1, 2, "Щитовидная железа", "ТТГ, св. Т4, св. Т3, АТ-ТПО, АТ-ТГ",
    ),
    "liver_panel": ProfileCatalogEntry(
        "liver_panel", P1, 2, "Печёночный профиль", "АЛТ, АСТ, ГГТ, ЩФ, билирубин, альбумин",
    ),
    "kidney_panel": ProfileCatalogEntry(
        "kidney_panel", P1, 2, "Почечный профиль", "Креатинин, мочевина, eGFR, альбумин/креатинин мочи",
    ),
    "inflammation_panel": ProfileCatalogEntry(
        "inflammation_panel", P1, 2, "Воспалительные маркеры", "CRP, hs-CRP, СОЭ, прокальцитонин",
    ),
    # --- P2 clinically strong (этап 3) ---
    "coagulation_panel": ProfileCatalogEntry(
        "coagulation_panel", P2, 3, "Коагулограмма", "ПТИ/INR, АЧТВ, фибриноген, D-димер",
    ),
    "vitamin_mineral_panel": ProfileCatalogEntry(
        "vitamin_mineral_panel", P2, 3, "Минеральный и костный обмен", "Ca, P, Mg, витамин D, ПТГ",
    ),
    "b12_folate_panel": ProfileCatalogEntry(
        "b12_folate_panel", P2, 3, "B12 / фолат / гомоцистеин", "B12, фолат, гомоцистеин, MMA",
    ),
    "reproductive_hormones_panel": ProfileCatalogEntry(
        "reproductive_hormones_panel", P2, 3, "Гормоны репродуктивной системы", "ФСГ, ЛГ, эстрадиол, прогестерон, пролактин, тестостерон, SHBG",
    ),
    "adrenal_panel": ProfileCatalogEntry(
        "adrenal_panel", P2, 3, "Надпочечники / стресс-ось", "Кортизол, АКТГ, ДГЭА-S",
    ),
    # --- P3 niche / advanced (этап 4) ---
    "organic_acids_urine": ProfileCatalogEntry(
        "organic_acids_urine", P3, 4, "Органические кислоты мочи", "Метаболом / органические кислоты",
    ),
    "amino_acids_panel": ProfileCatalogEntry(
        "amino_acids_panel", P3, 4, "Аминокислоты / метаболические панели", "Профили аминокислот",
    ),
    "autoimmune_panel": ProfileCatalogEntry(
        "autoimmune_panel", P3, 4, "Аутоиммунные маркеры", "ANA, ENA, RF, anti-CCP",
    ),
    "infectious_serology_panel": ProfileCatalogEntry(
        "infectious_serology_panel", P3, 4, "Инфекционная серология", "EBV, CMV, TORCH, гепатиты",
    ),
    "oncology_markers_panel": ProfileCatalogEntry(
        "oncology_markers_panel", P3, 4, "Онкомаркеры", "Только с жёсткими ограничениями и дисклеймерами",
    ),
    # Fallback
    "generic_lab": ProfileCatalogEntry(
        "generic_lab", P3, 4, "Общий лабораторный документ", "Не классифицирован",
    ),
}


def catalog_keys_for_priority(max_priority: int = P3) -> Tuple[str, ...]:
    """Ключи профилей с priority <= max_priority, отсортированные по (priority, key)."""
    items = [(e.key, e.priority) for e in PROFILE_CATALOG.values() if e.priority <= max_priority]
    items.sort(key=lambda x: (x[1], x[0]))
    return tuple(k for k, _ in items)


def expected_registry_keys() -> FrozenSet[str]:
    """Множество ключей, которые обязаны быть в PROFILE_REGISTRY (синхронно с каталогом)."""
    return frozenset(PROFILE_CATALOG.keys())
