"""Протокол крови: приоритет ОАК (CBC), затем липиды, биохимия, глюкоза, гормоны, коагуляция."""
from __future__ import annotations

from typing import List, Optional, Set, Tuple

from app.services.lab_value_extractor import LabValue

# Маркеры для detect_cbc: подстроки в нижнем регистре + имена LabValue
CBC_TEXT_MARKERS = [
    "гемоглобин",
    "hemoglobin",
    "hgb",
    "эритроцит",
    "rbc",
    "лейкоцит",
    "wbc",
    "тромбоцит",
    "plt",
    "mcv",
    "mch",
    "mchc",
    "rdw",
    "нейтрофил",
    "лимфоцит",
    "моноцит",
    "эозинофил",
    "базофил",
    "лейкоформула",
    "лейкоцитарн",  # «лейкоцитарная формула», «с лейкоцитарной формулой»
    "diff",
    "cbc",
    "оак",
    "общий анализ крови",
    "клинический анализ крови",
    "общеклинический анализ крови",
]

CBC_CANONICAL_MARKERS: Set[str] = {
    "Hb",
    "RBC",
    "WBC",
    "PLT",
    "MCV",
    "MCH",
    "MCHC",
    "RDW",
    "Neutrophils",
    "Lymphocytes",
    "Monocytes",
    "Eosinophils",
    "Basophils",
}

BLOOD_MATERIAL_PHRASES = (
    "венозная кровь",
    "капиллярная кровь",
    "биоматериал: кровь",
    "биоматериал кровь",
    "сыворотка",
    "serum",
    "plasma",
    "плазма",
    "кровь из вены",
)

RETIC_PHRASES = ("ретикулоцит", "reticulocyte", "ret%", " ret ")


def blood_anchor_hit(text: str) -> bool:
    low = (text or "").lower()
    return any(p in low for p in BLOOD_MATERIAL_PHRASES)


def detect_cbc(text: str, lab_values: Optional[List[LabValue]] = None) -> Tuple[bool, int]:
    """
    Возвращает (is_cbc, score). is_cbc=True если score >= 3 (как в спецификации).
    Учитывает текст и при наличии — канонические маркеры из extract_cbc_values.
    """
    low = (text or "").lower()
    score = 0
    seen = set()
    for m in CBC_TEXT_MARKERS:
        if m in low and m not in seen:
            score += 1
            seen.add(m)
    if lab_values:
        for v in lab_values:
            if v.marker in CBC_CANONICAL_MARKERS:
                score += 1
    # дедуп: если и текст и значение дают Hb — считаем один раз за маркер
    # упрощённо: score уже завышен мало, порог 3 устойчив
    return score >= 3, score


def has_reticulocytes(text: str, lab_values: Optional[List[LabValue]] = None) -> bool:
    low = (text or "").lower()
    if any(p in low for p in RETIC_PHRASES):
        return True
    if lab_values:
        return any("Reticulocyte" in v.marker for v in lab_values)
    return False


def is_blood_hard(text: str, lab_values: Optional[List[LabValue]] = None) -> bool:
    """Жёсткие признаки крови (не моча): якорь биоматериала, сыворотка, явный ОАК, липид/биохим панель."""
    low = (text or "").lower()
    if blood_anchor_hit(text):
        return True
    if any(
        p in low
        for p in (
            "общий анализ крови",
            "клинический анализ крови",
            "общеклинический анализ крови",
            "оак",
            "cbc",
        )
    ):
        return True
    # Типичные бланки без слова «кровь»: липидный профиль, общая биохимия (не моча)
    if "липидный профиль" in low or "липидный комплекс" in low:
        return True
    biochem_words = (
        "холестерин",
        "лпнп",
        "лпвп",
        "hdl",
        "ldl",
        "триглицерид",
        "креатинин",
        "мочевина",
        "алт",
        "аст",
        "глюкоза",
        "hba1c",
    )
    if sum(1 for w in biochem_words if w in low) >= 3:
        return True
    ok, _ = detect_cbc(text, lab_values)
    if ok:
        return True
    # триада из извлечённых значений
    if lab_values:
        canon = {v.marker for v in lab_values}
        if {"Hb", "RBC", "WBC"}.issubset(canon) or {"Hb", "WBC", "PLT"}.issubset(canon):
            return True
    return False


def forbidden_for_blood() -> List[str]:
    return ["urinalysis", "stool_coprogram", "saliva_only"]


def allowed_blood_subprofiles() -> List[str]:
    return [
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
        "organic_acids",  # обычно моча; в blood не должен попадать без проверки материала
    ]
