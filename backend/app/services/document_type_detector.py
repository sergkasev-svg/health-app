"""Детектор типа лабораторного анализа по тексту."""
from typing import Any, Dict, List, Literal, Optional

from app.services.clinical_engine.material_protocols.material_router import route_document
from app.services.lab_value_extractor import extract_cbc_values

# Ключи, совместимые с clinical_routing_engine.LAB_TYPE_TO_ROUTE
LAB_TYPE_ORGANIC_ACIDS = "organic_acids"
LAB_TYPE_LIPID = "lipid"
LAB_TYPE_CBC = "cbc"
LAB_TYPE_THYROID = "thyroid"
LAB_TYPE_BIOCHEMISTRY = "biochemistry_basic"
LAB_TYPE_URINE = "urine_general_route"
LAB_TYPE_IRON = "iron"

# Маппинг detect_report_type() -> ключ для clinical routing
_REPORT_TYPE_TO_LAB_KEY: Dict[str, str] = {
    "organic_acids": LAB_TYPE_ORGANIC_ACIDS,
    "lipid_panel": LAB_TYPE_LIPID,
    "cbc": LAB_TYPE_CBC,
    "cbc_with_reticulocytes": LAB_TYPE_CBC,
    "thyroid": LAB_TYPE_THYROID,
    "biochemistry": LAB_TYPE_BIOCHEMISTRY,
    "liver_panel": LAB_TYPE_BIOCHEMISTRY,
    "vitamin_panel": LAB_TYPE_BIOCHEMISTRY,
    "urinalysis": LAB_TYPE_URINE,
    "unknown": "",
}


ReportType = Literal[
    "organic_acids",
    "lipid_panel",
    "cbc",
    "cbc_with_reticulocytes",
    "biochemistry",
    "liver_panel",
    "thyroid",
    "vitamin_panel",
    "urinalysis",
    "unknown",
]

# Маркеры биохимии крови: если в тексте >= 3 — документ считаем biochemistry_blood,
# чтобы не классифицировать как organic_acids при общих фразах вроде «маркеры метаболизма».
BIOCHEM_MARKERS = [
    "холестерин",
    "лпнп",
    "ldl",
    "лпвп",
    "hdl",
    "триглицерид",
    "hba1c",
    "гликированн",
    "фруктозамин",
    "гомоцистеин",
    "crp",
    "с-реактивн",
]


def _count_biochem_matches(text: str) -> int:
    """Количество маркеров биохимии, найденных в тексте (без дублей по подстрокам)."""
    if not text:
        return 0
    low = text.lower()
    return sum(1 for m in BIOCHEM_MARKERS if m in low)


def detect_report_type(text: str) -> ReportType:
    """
    Определяет тип лабораторного анализа по тексту.
    Сначала material-first маршрутизатор (биоматериал → профиль; ОАК приоритетнее липидов/биохимии в крови),
    затем legacy-эвристики при unknown.
    """
    if not text:
        return "unknown"
    routed = route_document(text)
    if routed.report_type and routed.report_type != "unknown":
        return routed.report_type  # type: ignore[return-value]

    return _legacy_detect_report_type(text)


def _legacy_detect_report_type(text: str) -> ReportType:
    """
    Прежняя логика: биохимия (>=3 маркеров) → … → ОАМ → ОАК → …
    Используется, если material-router вернул unknown.
    """
    text_lower = text.lower()

    # Биохимия крови по маркерам: приоритет над organic_acids (избегаем ложной маршрутизации)
    if _count_biochem_matches(text_lower) >= 3:
        return "biochemistry"

    # Органические кислоты (специальный pipeline)
    organic_phrases = (
        "органических кислот",
        "органические кислоты в моче",
        "гх-мс",
        "organic_acids_urine",
        "маркеры углеводного обмена",
        "маркеры метаболизма",
        "миндальн",
        "ксантурен",
        "орот",
        "лимонн",
        "цитрат",
        "пируват",
        "ммоль/моль",
    )
    if any(p in text_lower for p in organic_phrases):
        return "organic_acids"

    # Липидный профиль
    lipid_phrases = (
        "липидный профиль",
        "липидный комплекс",
        "холестерин",
        "ldl",
        "лпнп",
        "hdl",
        "лпвп",
        "триглицерид",
        "апоб",
        "липопротеин",
        "атерогенн",
    )
    if any(p in text_lower for p in lipid_phrases):
        return "lipid_panel"

    # Общий анализ мочи (ОАМ) — до CBC, т.к. в ОАМ тоже есть лейкоциты/эритроциты
    urinalysis_markers = (
        "общий анализ мочи",
        "оам",
        "анализ мочи",
        "urinalysis",
        "биоматериал: моча",
        "моча (разовая)",
        "моча разовая",
        "ph",
        "относительная плотность",
        "плотность мочи",
        "белок ",
        "глюкоза ",
        "кетоны",
        "нитриты",
        "реакция на кровь",
        "эритроциты",
        "лейкоциты",
        "бактерии",
        "цилиндры",
        "слизь",
        "уробилиноген",
        "осадок",
    )
    urine_anchor = any(
        p in text_lower
        for p in (
            "общий анализ мочи",
            "оам",
            "анализ мочи",
            "urinalysis",
            "биоматериал: моча",
            "моча (разовая)",
        )
    )
    urine_marker_count = sum(1 for m in urinalysis_markers if m in text_lower)
    if urine_anchor and urine_marker_count >= 4:
        return "urinalysis"
    if urine_marker_count >= 5:
        return "urinalysis"

    # Общий анализ крови (ОАК); при наличии ретикулоцитов — cbc_with_reticulocytes
    cbc_phrases = (
        "общий анализ крови",
        "клинический анализ крови",
        "общеклинический анализ крови",
        "лейкоцитарной формулой",
        "лейкоцитарная формула",
        "анализ крови",
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
        "нейтрофил",
        "лимфоцит",
        "моноцит",
        "эозинофил",
        "базофил",
    )
    # «общий анализ» без «моч» — кровь; лейкоцит/эритроцит только если нет явного ОАМ
    has_blood_anchor = any(
        p in text_lower
        for p in (
            "общий анализ крови",
            "клинический анализ крови",
            "общеклинический анализ крови",
            "оак",
            "cbc",
            "гемоглобин",
            "гематокрит",
            "тромбоцит",
            "mcv",
            "mch",
            "rdw",
        )
    )
    has_cbc_phrases = any(p in text_lower for p in cbc_phrases)
    has_urine_context = "моч" in text_lower or "оам" in text_lower or "urinalysis" in text_lower
    reticulocyte_phrases = ("ретикулоцит", "reticulocyte", "ret%", "ret ")
    has_reticulocytes = any(p in text_lower for p in reticulocyte_phrases)
    if has_cbc_phrases and not has_urine_context:
        return "cbc_with_reticulocytes" if has_reticulocytes else "cbc"
    if has_blood_anchor:
        return "cbc_with_reticulocytes" if has_reticulocytes else "cbc"

    # Печёночные пробы
    liver_phrases = (
        "печёночные пробы",
        "печеночные пробы",
        "алт",
        "аст",
        "билирубин",
        "щелочная фосфатаза",
        "альбумин",
        "протромбин",
        "мно",
    )
    if any(p in text_lower for p in liver_phrases):
        return "liver_panel"

    # Биохимия (общая)
    biochemistry_phrases = (
        "биохимический анализ",
        "биохимия",
        "глюкоза",
        "креатинин",
        "мочевина",
        "мочевая кислота",
        "общий белок",
        "электролит",
        "натрий",
        "калий",
        "хлор",
    )
    if any(p in text_lower for p in biochemistry_phrases):
        return "biochemistry"

    # Щитовидная железа
    thyroid_phrases = (
        "тиреотропный",
        "ттг",
        "тироксин",
        "т4",
        "трийодтиронин",
        "т3",
        "антитела к тпо",
        "антитела к тг",
    )
    if any(p in text_lower for p in thyroid_phrases):
        return "thyroid"

    # Витамины
    vitamin_phrases = (
        "витамин",
        "вит.",
        "b12",
        "фолат",
        "фолиевая",
        "25-oh витамин d",
        "витамин d",
        "вит d",
    )
    if any(p in text_lower for p in vitamin_phrases):
        return "vitamin_panel"

    return "unknown"


def classify_by_cbc_markers(extracted_text: str) -> Optional[ReportType]:
    """
    Классификация по извлечённым маркерам: если в тексте найдено >= 6 CBC-показателей,
    тип — cbc; при наличии ретикулоцитов — cbc_with_reticulocytes.
    Используется когда detect_report_type вернул unknown (нет фраз в тексте).
    """
    if not (extracted_text or "").strip():
        return None
    values = extract_cbc_values(extracted_text.strip())
    if len(values) < 6:
        return None
    has_reticulocytes = any("Reticulocyte" in v.marker for v in values)
    return "cbc_with_reticulocytes" if has_reticulocytes else "cbc"


def detect_lab_type(
    text: str,
    filename: Optional[str] = None,
) -> List[str]:
    """
    Возвращает список типов лабораторных панелей по тексту (и опционально имени файла).
    Совместим с clinical_routing_engine: ключи как в LAB_TYPE_TO_ROUTE.
    """
    report_type = detect_report_type(text or "")
    lab_key = _REPORT_TYPE_TO_LAB_KEY.get(report_type, "")
    if not lab_key:
        # По имени файла можно добавить подсказки
        if filename:
            fn_lower = (filename or "").lower()
            if "липид" in fn_lower or "холестерин" in fn_lower or "lipid" in fn_lower:
                return [LAB_TYPE_LIPID]
            if "оак" in fn_lower or "кровь" in fn_lower or "cbc" in fn_lower:
                return [LAB_TYPE_CBC]
            if "моча" in fn_lower or "urine" in fn_lower:
                return [LAB_TYPE_URINE]
        return []
    return [lab_key]


def prioritize_lab_types(raw_lab_list: List[str]) -> List[str]:
    """
    Приоритизация списка типов панелей (например, organic_acids и lipid выше).
    Совместим с clinical_routing_engine.
    """
    if not raw_lab_list:
        return []
    order = [
        LAB_TYPE_ORGANIC_ACIDS,
        LAB_TYPE_LIPID,
        LAB_TYPE_CBC,
        LAB_TYPE_THYROID,
        LAB_TYPE_BIOCHEMISTRY,
        LAB_TYPE_IRON,
        LAB_TYPE_URINE,
    ]
    seen = set()
    result: List[str] = []
    for key in order:
        if key in raw_lab_list and key not in seen:
            result.append(key)
            seen.add(key)
    for key in raw_lab_list:
        if key not in seen:
            result.append(key)
            seen.add(key)
    return result


def detect_document_type(
    text: str,
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Определяет тип документа по тексту и имени файла.
    Возвращает dict с ключом lab_types (список) для совместимости с clinical_routing_engine.
    Дополнительно: material, material_confidence, material_routing (material-first слой).
    """
    raw_lab_list = detect_lab_type(text, filename)
    lab_list = prioritize_lab_types(raw_lab_list)
    routed = route_document(text or "")
    return {
        "lab_types": lab_list,
        "report_type": detect_report_type(text or ""),
        "raw_lab_list": raw_lab_list,
        "material": routed.material.value,
        "material_confidence": routed.material_confidence,
        "material_routing": routed.model_dump(),
    }
