"""
Material-first маршрутизатор: document → material → report_type (профиль).

Правила:
- Сначала биоматериал, затем профиль (Material > Profile).
- Для крови: ОАК/CBC имеет наивысший приоритет над липидами и биохимией.
- Моча: не маршрутизировать в CBC (urinalysis только).
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from app.services.clinical_engine.material_protocols.blood_protocol import (
    allowed_blood_subprofiles,
    detect_cbc,
    forbidden_for_blood,
    has_reticulocytes,
    is_blood_hard,
)
from app.services.clinical_engine.material_protocols.contract import MaterialKind, MaterialRoutingResult
from app.services.clinical_engine.material_protocols.saliva_protocol import is_saliva
from app.services.clinical_engine.material_protocols.stool_protocol import is_strong_stool
from app.services.clinical_engine.material_protocols.swab_protocol import is_strong_swab
from app.services.clinical_engine.material_protocols.urine_protocol import (
    is_strong_urine,
    urine_anchor_hit,
    urine_marker_count as urine_kw_count,
)
from app.services.clinical_engine.contracts import DocumentType
from app.services.lab_value_extractor import LabValue, extract_cbc_values

# Совпадает с document_type_detector.BIOCHEM_MARKERS для согласованности
_BIOCHEM_MARKERS = [
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
    if not text:
        return 0
    low = text.lower()
    return sum(1 for m in _BIOCHEM_MARKERS if m in low)


def _organic_acids_hit(text: str) -> bool:
    low = (text or "").lower()
    organic_phrases = (
        "органических кислот",
        "органические кислоты в моче",
        "гх-мс",
        "organic_acids_urine",
        "маркеры углеводного обмена",
        "миндальн",
        "ксантурен",
        "орот",
        "лимонн",
        "цитрат",
        "пируват",
        "ммоль/моль",
    )
    return any(p in low for p in organic_phrases)


def _lipid_panel_explicit(text: str) -> bool:
    low = (text or "").lower()
    return "липидный профиль" in low or "липидный комплекс" in low


def _oak_form_title_primary(text: str) -> bool:
    """
    Заголовок бланка как у ОАК (не колонтитул/реклама).
    Если он есть вместе с блоком «липидный профиль», нельзя показывать тип документа как «только липиды».
    """
    low = (text or "").lower()
    phrases = (
        "общеклинический анализ крови",
        "общий анализ крови",
        "клинический анализ крови",
        "лейкоцитарной формулой",
        "лейкоцитарная формула",
    )
    return any(p in low for p in phrases)


def _lipid_hit(text: str) -> bool:
    low = (text or "").lower()
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
    return any(p in low for p in lipid_phrases)


def _liver_hit(text: str) -> bool:
    low = (text or "").lower()
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
    return any(p in low for p in liver_phrases)


def _thyroid_hit(text: str) -> bool:
    low = (text or "").lower()
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
    return any(p in low for p in thyroid_phrases)


def _vitamin_hit(text: str) -> bool:
    low = (text or "").lower()
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
    return any(p in low for p in vitamin_phrases)


def _biochemistry_general_hit(text: str) -> bool:
    low = (text or "").lower()
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
    return any(p in low for p in biochemistry_phrases)


def route_blood_profile(
    text: str,
    lab_values: Optional[List[LabValue]] = None,
) -> Tuple[str, Optional[str], bool, List[str]]:
    """
    Возвращает (report_type, blood_subprofile, cbc_override, reasons).
    Приоритет: явный «липидный профиль» + ОАК в одном файле → lipid_panel (ОАК merge),
    иначе CBC → … → липиды по маркерам.
    Если на бланке явный заголовок ОАК и отдельный блок «липидный профиль» — biochemistry_blood
    (router даст lipid_panel при наличии липидных значений; doc_type остаётся biochemistry_blood для корректной подписи).
    """
    reasons: List[str] = []
    cbc_ok, cbc_score = detect_cbc(text, lab_values)
    # Мультиблок: липидный заголовок и формула крови — по умолчанию lipid_panel; ОАК догоняет merge-слой.
    # Исключение: основной заголовок бланка — ОАК → не навязывать document_type=lipid_panel (иначе в отчёте «Липидный профиль»).
    if cbc_ok and _lipid_panel_explicit(text):
        if _oak_form_title_primary(text):
            reasons.append(
                "заголовок ОАК/общеклинический анализ + блок «липидный профиль» → biochemistry; "
                "интерпретация липидов через profile=lipid_panel, тип документа — biochemistry_blood"
            )
            return "biochemistry", "biochemistry", False, reasons
        reasons.append(
            "липидный бланк (явный заголовок) и ОАК в одном файле → lipid_panel; ОАК подмешивается при merge"
        )
        return "lipid_panel", "lipid", False, reasons

    if cbc_ok:
        retic = has_reticulocytes(text, lab_values)
        rt = "cbc_with_reticulocytes" if retic else "cbc"
        reasons.append(f"CBC: score>={cbc_score} (порог 3), приоритет над липидами/биохимией")
        return rt, "cbc_retic" if retic else "cbc", True, reasons

    # Явный липидный бланк — раньше общего «>=3 биохимических слов» (холестерин+ЛПНП+ЛПВП)
    if _lipid_panel_explicit(text):
        reasons.append("липидный профиль / комплекс (явный заголовок)")
        return "lipid_panel", "lipid", False, reasons

    if _count_biochem_matches(text) >= 3:
        reasons.append("биохимия: >=3 маркеров из набора")
        return "biochemistry", "biochemistry", False, reasons

    if _organic_acids_hit(text):
        reasons.append("органические кислоты (сигнатура)")
        return "organic_acids", "organic_acids", False, reasons

    if _lipid_hit(text):
        reasons.append("липидные фразы")
        return "lipid_panel", "lipid", False, reasons

    if _liver_hit(text):
        return "liver_panel", "liver", False, reasons

    if _thyroid_hit(text):
        return "thyroid", "thyroid", False, reasons

    if _vitamin_hit(text):
        return "vitamin_panel", "vitamin", False, reasons

    if _biochemistry_general_hit(text):
        return "biochemistry", "biochemistry", False, reasons

    return "unknown", None, False, reasons


def report_type_to_document_type(report_type: str) -> Optional[DocumentType]:
    """Маппинг строки detect_report_type → enum для classify_document / pipeline."""
    m: dict[str, DocumentType] = {
        "cbc": DocumentType.CBC,
        "cbc_with_reticulocytes": DocumentType.CBC_RETIC,
        "biochemistry": DocumentType.BIOCHEMISTRY_BLOOD,
        "lipid_panel": DocumentType.LIPID_PANEL,
        "liver_panel": DocumentType.BIOCHEMISTRY_BLOOD,
        "thyroid": DocumentType.THYROID_PANEL,
        "vitamin_panel": DocumentType.BIOCHEMISTRY_BLOOD,
        "organic_acids": DocumentType.ORGANIC_ACIDS_URINE,
        "urinalysis": DocumentType.URINALYSIS,
    }
    return m.get(report_type)


def route_document(text: str, lab_values: Optional[List[LabValue]] = None) -> MaterialRoutingResult:
    """
    Главный вход material-first. Если уверенность низкая — report_type может остаться unknown
    (тогда сработает legacy detect_report_type).
    """
    if not (text or "").strip():
        return MaterialRoutingResult(
            material=MaterialKind.UNKNOWN,
            material_confidence=0.0,
            report_type="unknown",
            reasons=["пустой текст"],
        )

    low = text.lower()
    values = lab_values if lab_values is not None else extract_cbc_values(text)

    reasons: List[str] = []
    forbidden: List[str] = []
    allowed: List[str] = []

    u_hard = is_strong_urine(text)
    b_hard = is_blood_hard(text, values)
    stool = is_strong_stool(text)
    saliva = is_saliva(text)
    swab = is_strong_swab(text)

    # Конфликт: явная моча и явная кровь
    if u_hard and b_hard:
        # Правило: явный ОАК в тексте → кровь и маршрут как blood; иначе якорь ОАМ без ОАК → моча
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
            reasons.append("конфликт моча/кровь: выбрана кровь (явный ОАК)")
            rt, sub, cbc_ov, br = route_blood_profile(text, values)
            reasons.extend(br)
            forb = ["urinalysis", "stool_coprogram"]
            if rt != "unknown":
                return MaterialRoutingResult(
                    material=MaterialKind.BLOOD,
                    material_confidence=0.88,
                    report_type=rt,
                    blood_subprofile=sub,
                    reasons=reasons,
                    allowed_profiles=allowed_blood_subprofiles(),
                    forbidden_profiles=forb,
                    cbc_override=cbc_ov,
                )
        elif (
            (urine_anchor_hit(text) or urine_kw_count(text) >= 4)
            and not any(
                p in low
                for p in (
                    "общий анализ крови",
                    "клинический анализ крови",
                    "общеклинический анализ крови",
                    "оак",
                    "cbc",
                    "гематокрит",
                )
            )
        ):
            reasons.append("конфликт моча/кровь: выбрана моча (якорь/много маркеров ОАМ без ОАК)")
            return MaterialRoutingResult(
                material=MaterialKind.URINE,
                material_confidence=0.88,
                report_type="urinalysis",
                reasons=reasons,
                allowed_profiles=["urinalysis", "organic_acids_urine", "microalbumin_urine"],
                forbidden_profiles=forbidden_for_blood(),
            )
        return MaterialRoutingResult(
            material=MaterialKind.CONFLICT,
            material_confidence=0.4,
            report_type="unknown",
            reasons=reasons + ["конфликт моча/кровь: требуется уточнение"],
            forbidden_profiles=forbidden_for_blood() + ["urinalysis"],
            conflict_note="urine_vs_blood",
        )
    if stool and not b_hard:
        material = MaterialKind.STOOL
        reasons.append("признаки кала/копрограммы")
        return MaterialRoutingResult(
            material=material,
            material_confidence=0.85,
            report_type="unknown",
            reasons=reasons,
            allowed_profiles=["coprogram", "occult_blood", "parasites"],
            forbidden_profiles=forbidden_for_blood() + ["urinalysis", "cbc"],
            conflict_note="stool_no_engine",
        )
    if saliva and not (b_hard or u_hard):
        material = MaterialKind.SALIVA
        reasons.append("слюна")
        return MaterialRoutingResult(
            material=material,
            material_confidence=0.75,
            report_type="unknown",
            reasons=reasons,
            allowed_profiles=["cortisol_saliva", "hormone_saliva"],
            forbidden_profiles=forbidden_for_blood() + ["urinalysis"],
        )
    if swab and not (b_hard or u_hard):
        material = MaterialKind.SWAB
        reasons.append("мазок/ПЦР")
        return MaterialRoutingResult(
            material=material,
            material_confidence=0.75,
            report_type="unknown",
            reasons=reasons,
            allowed_profiles=["pcr_swab", "urogenital_swab"],
        )
    if u_hard and not b_hard:
        material = MaterialKind.URINE
        reasons.append("моча: якорь или сильные маркеры ОАМ")
        forbidden = forbidden_for_blood()
        return MaterialRoutingResult(
            material=material,
            material_confidence=0.92,
            report_type="urinalysis",
            reasons=reasons,
            allowed_profiles=["urinalysis", "organic_acids_urine", "microalbumin_urine"],
            forbidden_profiles=forbidden,
        )
    if b_hard or (not u_hard and detect_cbc(text, values)[0]):
        material = MaterialKind.BLOOD
        reasons.append("кровь: биоматериал/ОАК/CBC-маркеры")
        allowed = allowed_blood_subprofiles()
        rt, sub, cbc_ov, br = route_blood_profile(text, values)
        reasons.extend(br)
        forb = ["urinalysis", "stool_coprogram"]
        if rt != "unknown":
            return MaterialRoutingResult(
                material=material,
                material_confidence=0.9 if cbc_ov else 0.82,
                report_type=rt,
                blood_subprofile=sub,
                reasons=reasons,
                allowed_profiles=allowed,
                forbidden_profiles=forb,
                cbc_override=cbc_ov,
            )
        return MaterialRoutingResult(
            material=material,
            material_confidence=0.55,
            report_type="unknown",
            blood_subprofile=sub,
            reasons=reasons + ["blood без однозначного подпрофиля"],
            allowed_profiles=allowed,
            forbidden_profiles=forb,
        )

    # Слабые сигналы — не навязываем материал
    return MaterialRoutingResult(
        material=MaterialKind.UNKNOWN,
        material_confidence=0.3,
        report_type="unknown",
        reasons=["материал не определён однозначно — fallback legacy"],
    )
