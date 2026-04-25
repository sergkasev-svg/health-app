"""
Rule-based classifier типа документа.
Приоритет: biochemistry_blood по маркерам (>=3), затем organic_acids только по явной сигнатуре.
"""
from __future__ import annotations

from app.services.clinical_engine.contracts import DocumentType
from app.services.clinical_engine.material_protocols.material_router import (
    report_type_to_document_type,
    route_document,
)


# Продакшен-наборы для rule-based first classifier (спека)
BIOCHEM_MARKERS = {
    "холестерин",
    "лпнп",
    "лпвп",
    "триглицериды",
    "hba1c",
    "гликированный гемоглобин",
    "фруктозамин",
    "гомоцистеин",
    "с-реактивный белок",
    "аполипопротеин",
}
# для count_hits: подстроки в нижнем регистре
BIOCHEM_MARKERS_LOWER = {m.lower() for m in BIOCHEM_MARKERS}

# Явная сигнатура органических кислот мочи — только тогда organic_acids_urine
ORGANIC_ACID_MARKERS = {
    "органические кислоты",
    "моча",
    "метилмалоновая",
    "пировиноградная",
    "сукцинат",
    "арабиноза",
}

# Расширенные списки для подсчёта (подстроки)
BIOCHEM_BLOOD_MARKERS = list(BIOCHEM_MARKERS) + [
    "ldl",
    "hdl",
    "триглицерид",
    "гликированн",
    "гликозилированн",
    "crp",
    "с-реактивн",
    "apob",
    "apo_b",
    "apo a1",
    "липопротеин (а)",
    "lp(a)",
]
ORGANIC_ACIDS_SIGNATURE = list(ORGANIC_ACID_MARKERS) + [
    "органические кислоты в моче",
    "органических кислот",
    "гх-мс",
    "газохроматография",
    "3-гидроксимасляная",
    "оксалоуксусная",
    "кетокислот",
    "миндальн",
    "ксантурен",
    "оротовая",
    "лимонн",
    "цитрат",
    "пируват",
    "ммоль/моль креатинин",
]


def count_hits(text: str, markers: set[str] | None = None) -> int:
    """Количество маркеров из набора, встретившихся в тексте (для спеки)."""
    t = (text or "").lower()
    if markers is None:
        markers = BIOCHEM_MARKERS_LOWER
    return sum(1 for m in markers if m in t)


def _count_matches(text: str, markers: list[str]) -> int:
    low = (text or "").lower()
    return sum(1 for m in markers if m in low)


def classify_document(text: str) -> DocumentType:
    """
    Определяет тип документа по тексту.
    Сначала material-first router (биоматериал → профиль; в крови CBC приоритетнее липидов/биохимии),
    затем прежние rule-based правила при необходимости.
    """
    if not (text or "").strip():
        return DocumentType.GENERIC_LAB

    routed = route_document(text)
    mapped = report_type_to_document_type(routed.report_type)
    if mapped is not None:
        return mapped

    low = text.strip().lower()

    # 1. Biochemistry blood — приоритет: >=3 маркеров из набора (спека)
    if count_hits(low, BIOCHEM_MARKERS_LOWER) >= 3:
        return DocumentType.BIOCHEMISTRY_BLOOD
    if _count_matches(low, BIOCHEM_BLOOD_MARKERS) >= 3:
        return DocumentType.BIOCHEMISTRY_BLOOD

    # 2. Organic acids — только при явной сигнатуре (>=3 из набора или фразы)
    oa_set = {m.lower() for m in ORGANIC_ACID_MARKERS}
    if count_hits(low, oa_set) >= 3:
        return DocumentType.ORGANIC_ACIDS_URINE
    if any(p in low for p in ORGANIC_ACIDS_SIGNATURE):
        return DocumentType.ORGANIC_ACIDS_URINE

    # 3. ОАК / CBC раньше липидов: на комбинированных бланках и при «общеклинический … с лейкоцитарной формулой»
    #    не уводить документ в липиды из‑за слов «липопротеин»/«холестерин» в рекламе или другом блоке.
    cbc_phrases = (
        "общий анализ крови",
        "клинический анализ крови",
        "общеклинический анализ крови",
        "лейкоцитарной формулой",
        "лейкоцитарная формула",
        "оак",
        "cbc",
        "лейкоцит",
        "эритроцит",
        "гемоглобин",
        "гематокрит",
        "тромбоцит",
        "mcv",
        "mch",
        "rdw",
    )
    reticulocyte_phrases = ("ретикулоцит", "reticulocyte", "ret%")
    if any(p in low for p in cbc_phrases):
        return DocumentType.CBC_RETIC if any(p in low for p in reticulocyte_phrases) else DocumentType.CBC

    # 4. Липидный профиль (отдельные фразы без 3+ общих биохимических маркеров)
    lipid_phrases = (
        "липидный профиль",
        "липидный комплекс",
        "холестерин",
        "лпнп",
        "лпвп",
        "триглицерид",
        "апоб",
        "липопротеин",
    )
    if any(p in low for p in lipid_phrases):
        return DocumentType.LIPID_PANEL

    # 5. Щитовидная железа
    thyroid_phrases = ("тиреотропный", "ттг", "тироксин", "т4", "трийодтиронин", "т3", "тпо", "ат к тг")
    if any(p in low for p in thyroid_phrases):
        return DocumentType.THYROID_PANEL

    # 6. Моча общая (после ОАК/липидов)
    urine_phrases = ("общий анализ мочи", "анализ мочи", "urinalysis")
    if any(p in low for p in urine_phrases):
        return DocumentType.URINALYSIS

    return DocumentType.GENERIC_LAB
