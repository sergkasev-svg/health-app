"""
Матрица клинических профилей «За Здоровье»: маркеры, паттерны, risk, next steps.
Каркас для rule engine + risk + приоритизации; ключи совпадают с profile_registry / profile_catalog.

Использование:
  from app.services.clinical_engine.profile_matrix import get_matrix_entry, PROFILE_MATRIX

Следующие шаги внедрения (продукт):
  1) P0: CBC, Urinalysis, Lipid, Glucose, Biochemistry — довести правила до parity с матрицей
  2) P1: Iron, Thyroid (+ liver, kidney, inflammation)
  3) Единый risk scoring + UI routing
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Tuple

# Уровни риска для сопоставления с OverallRisk / rule engine
RISK_LOW = "low"
RISK_MODERATE = "moderate"
RISK_HIGH = "high"
RISK_URGENT = "urgent"
RISK_CONTEXTUAL = "contextual"
# Диапазон типичного уровня (клинический контекст)
RISK_LOW_TO_MODERATE = "low_to_moderate"
RISK_MODERATE_TO_HIGH = "moderate_to_high"


@dataclass(frozen=True)
class RiskRuleSpec:
    """Одно правило оценки риска (условие → типичный уровень)."""

    rule_id: str
    condition_ru: str
    typical_level: str


@dataclass(frozen=True)
class ProfileMatrixEntry:
    """Полная строка матрицы для одного профиля."""

    profile_key: str
    priority: int  # 0=P0 … 3=P3 (как profile_registry)
    title_ru: str
    marker_codes: Tuple[str, ...]
    patterns_ru: Tuple[str, ...]
    risk_rules: Tuple[RiskRuleSpec, ...]
    next_steps_ru: Tuple[str, ...]
    engine_notes_ru: str = ""


def _r(rule_id: str, condition: str, level: str) -> RiskRuleSpec:
    return RiskRuleSpec(rule_id=rule_id, condition_ru=condition, typical_level=level)


# ---------------------------------------------------------------------------
# P0 — ядро
# ---------------------------------------------------------------------------

MATRIX_CBC = ProfileMatrixEntry(
    profile_key="cbc",
    priority=0,
    title_ru="ОАК (CBC)",
    marker_codes=(
        "hemoglobin",
        "rbc",
        "hct",
        "mcv",
        "mch",
        "mchc",
        "rdw",
        "wbc",
        "neutrophils",
        "lymphocytes",
        "monocytes",
        "eosinophils",
        "basophils",
        "plt",
        "esr",
    ),
    patterns_ru=(
        "анемия (микро / нормо / макро)",
        "воспалительный сдвиг лейкоцитарной формулы",
        "эозинофилия",
        "тромбоцитоз / тромбоцитопения",
        "нейтрофилез + СОЭ",
    ),
    risk_rules=(
        _r("cbc_severe_anemia", "выраженная анемия (контекст Hb)", RISK_HIGH),
        _r("cbc_neutrophilia_esr", "нейтрофилез + повышенная СОЭ", RISK_MODERATE),
        _r("cbc_neutrophilia_esr_high", "нейтрофилез + СОЭ (выраженный воспалительный контекст)", RISK_MODERATE_TO_HIGH),
        _r("cbc_isolated_esr", "изолированно повышенная СОЭ", RISK_LOW_TO_MODERATE),
    ),
    next_steps_ru=(
        "ферритин, сывороточное железо (при подозрении на дефицит железа)",
        "CRP / hs-CRP при воспалительном контексте",
        "повтор ОАК в динамике",
    ),
    engine_notes_ru="Ретикулоциты — расширение: профиль cbc_with_reticulocytes.",
)

MATRIX_URINALYSIS = ProfileMatrixEntry(
    profile_key="urinalysis",
    priority=0,
    title_ru="ОАМ (Urinalysis)",
    marker_codes=(
        "urine_ph",
        "urine_specific_gravity",
        "urine_protein",
        "urine_glucose",
        "urine_ketones",
        "urine_nitrites",
        "urine_leukocytes",
        "urine_blood",
        "urine_erythrocytes",
        "urine_bacteria",
    ),
    patterns_ru=(
        "ИМП-паттерн (лейкоциты / нитриты / бактерии)",
        "гематурия / реакция на кровь",
        "протеинурия",
        "глюкозурия / кетонурия",
        "разбавленная моча (низкая относительная плотность)",
    ),
    risk_rules=(
        _r("ua_infection_pattern", "инфекционный паттерн мочевых путей", RISK_MODERATE),
        _r("ua_isolated_blood", "изолированный слабый сигнал по крови без эритроцитов", RISK_LOW),
        _r("ua_proteinuria", "протеинурия", RISK_MODERATE),
    ),
    next_steps_ru=(
        "повтор ОАМ при жалобах или в динамике",
        "при симптомах со стороны мочевых путей — очная оценка врача",
        "при стойкой реакции на кровь — контроль и уточнение по клинике",
    ),
)

MATRIX_BIOCHEMISTRY = ProfileMatrixEntry(
    profile_key="biochemistry_blood",
    priority=0,
    title_ru="Биохимия крови (база)",
    marker_codes=(
        "alt",
        "ast",
        "bilirubin_total",
        "creatinine",
        "urea",
        "total_protein",
        "albumin",
        "glucose",
        "uric_acid",
    ),
    patterns_ru=(
        "печёночный паттерн (АЛТ/АСТ/билирубин)",
        "почечный паттерн (креатинин/мочевина)",
        "катаболизм / обезвоживание (контекст мочевины, белка)",
    ),
    risk_rules=(
        _r("bio_alt_ast_3x", "АЛТ/АСТ >3× ВРН (оценка по референсу лаборатории)", RISK_HIGH),
        _r("bio_creatinine_up", "креатинин повышен", RISK_MODERATE_TO_HIGH),
    ),
    next_steps_ru=(
        "расширенная биохимия при отклонениях",
        "оценка eGFR / почечный контекст",
        "повтор анализа в динамике",
    ),
)

MATRIX_LIPID = ProfileMatrixEntry(
    profile_key="lipid_panel",
    priority=0,
    title_ru="Липидный профиль",
    marker_codes=(
        "total_cholesterol",
        "ldl_cholesterol",
        "hdl_cholesterol",
        "triglycerides",
        "non_hdl_cholesterol",
        "apolipoprotein_b",
        "apolipoprotein_a1",
        "lipoprotein_a",
    ),
    patterns_ru=(
        "атерогенная дислипидемия",
        "подозрение на семейную гиперхолестеринемию (контекст ЛПНП/Lp(a))",
        "гипертриглицеридемия",
    ),
    risk_rules=(
        _r("lip_ldl_5", "ЛПНП >5 ммоль/л (или эквивалент по референсу)", RISK_HIGH),
        _r("lip_total_7", "общий холестерин >7 ммоль/л", RISK_HIGH),
        _r("lip_tg_up", "выраженное повышение триглицеридов", RISK_MODERATE),
    ),
    next_steps_ru=(
        "ApoB при выраженной атерогенности",
        "повтор липидограммы натощак",
        "ТТГ / метаболический контекст по показаниям",
    ),
)

MATRIX_GLUCOSE = ProfileMatrixEntry(
    profile_key="glucose_metabolism",
    priority=0,
    title_ru="Углеводный обмен",
    marker_codes=(
        "glucose",
        "hba1c",
        "fructosamine",
        "insulin",
        "c_peptide",
        "homa_ir",
    ),
    patterns_ru=(
        "преддиабет (по HbA1c / глюкозе)",
        "диабетический паттерн",
        "инсулинорезистентность (HOMA-IR, инсулин)",
        "расхождение краткосрочной и долгосрочной гликемии (фруктозамин vs HbA1c)",
    ),
    risk_rules=(
        _r("glu_hba1c_65", "HbA1c ≥6.5% (или по референсу лаборатории на диабет)", RISK_HIGH),
        _r("glu_discordance", "значимое расхождение маркеров гликемии", RISK_MODERATE),
    ),
    next_steps_ru=(
        "HOMA-IR / инсулин при показаниях",
        "повтор гликемических маркеров",
        "глюкоза натощак в динамике",
    ),
)

# ---------------------------------------------------------------------------
# P1
# ---------------------------------------------------------------------------

MATRIX_IRON = ProfileMatrixEntry(
    profile_key="iron_panel",
    priority=1,
    title_ru="Железный обмен",
    marker_codes=("ferritin", "serum_iron", "transferrin", "tibc", "transferrin_saturation"),
    patterns_ru=(
        "латентный дефицит железа",
        "явный дефицит железа",
        "воспалительный блок (высокий ферритин при анемии)",
    ),
    risk_rules=(
        _r("iron_ferritin_15", "ферритин <15 нг/мл (контекстно)", RISK_HIGH),
        _r("iron_low_anemia", "низкие показатели железа + анемия", RISK_HIGH),
    ),
    next_steps_ru=("контроль железного профиля", "B12/фолат при макроцитозе / по показаниям"),
)

MATRIX_THYROID = ProfileMatrixEntry(
    profile_key="thyroid_panel",
    priority=1,
    title_ru="Щитовидная железа",
    marker_codes=("tsh", "free_t4", "free_t3", "anti_tpo", "anti_tg"),
    patterns_ru=("гипотиреоз", "тиреотоксический паттерн", "АИТ (антитела)"),
    risk_rules=(
        _r("thy_tsh_10", "ТТГ >10 мМЕ/л (контекстно)", RISK_HIGH),
        _r("thy_tsh_01", "ТТГ <0.1 мМЕ/л (контекстно)", RISK_HIGH),
    ),
    next_steps_ru=("повтор с интервалом по клинике", "антитела / УЗИ — по показаниям врача"),
)

MATRIX_LIVER = ProfileMatrixEntry(
    profile_key="liver_panel",
    priority=1,
    title_ru="Печёночный профиль",
    marker_codes=("alt", "ast", "ggt", "alp", "bilirubin_total", "bilirubin_direct", "albumin"),
    patterns_ru=("гепатоцеллюлярный паттерн", "холестаз", "смешанный"),
    risk_rules=(_r("liv_enzymes_3x", "АЛТ/АСТ/ГГТ >3× ВРН", RISK_HIGH),),
    next_steps_ru=("УЗИ брюшной полости — по показаниям", "расширенный печёночный профиль"),
)

MATRIX_KIDNEY = ProfileMatrixEntry(
    profile_key="kidney_panel",
    priority=1,
    title_ru="Почечный профиль",
    marker_codes=("creatinine", "urea", "egfr", "urine_albumin_creatinine_ratio", "urine_protein"),
    patterns_ru=("снижение функции почек (CKD-контекст)", "альбуминурия / нефропатический сигнал"),
    risk_rules=(
        _r("kid_egfr_60", "eGFR <60", RISK_MODERATE),
        _r("kid_egfr_30", "eGFR <30", RISK_HIGH),
    ),
    next_steps_ru=("контроль креатинина/eGFR", "нефролог — по показаниям"),
)

MATRIX_INFLAMMATION = ProfileMatrixEntry(
    profile_key="inflammation_panel",
    priority=1,
    title_ru="Воспалительные маркеры",
    marker_codes=("crp", "hs_crp", "esr", "procalcitonin"),
    patterns_ru=("острое воспаление", "хронический воспалительный сигнал (hs-CRP)"),
    risk_rules=(_r("inf_crp_10", "CRP >10 мг/л (контекстно)", RISK_HIGH),),
    next_steps_ru=("поиск причины воспаления", "повтор в динамике"),
)

# ---------------------------------------------------------------------------
# P2 — кратко (тот же контракт)
# ---------------------------------------------------------------------------

MATRIX_B12_FOLATE = ProfileMatrixEntry(
    profile_key="b12_folate_panel",
    priority=2,
    title_ru="B12 / фолат / гомоцистеин",
    marker_codes=("vitamin_b12", "folate", "homocysteine", "mma"),
    patterns_ru=("мегалобластический контекст", "дефицит B12/фолата"),
    risk_rules=(_r("b12_macro", "сочетание с макроцитозом в ОАК", RISK_MODERATE),),
    next_steps_ru=("контроль", "корреляция с ОАК"),
)

MATRIX_VITAMIN_MINERAL = ProfileMatrixEntry(
    profile_key="vitamin_mineral_panel",
    priority=2,
    title_ru="Витамины / минералы",
    marker_codes=("vitamin_d", "calcium", "phosphorus", "magnesium", "pth"),
    patterns_ru=("дефицит витамина D", "нарушения кальций-фосфорного обмена"),
    risk_rules=(_r("vit_d_severe", "выраженный дефицит D", RISK_LOW_TO_MODERATE),),
    next_steps_ru=("коррекция по врачу", "контроль 25(OH)D"),
)

MATRIX_COAGULATION = ProfileMatrixEntry(
    profile_key="coagulation_panel",
    priority=2,
    title_ru="Коагулограмма",
    marker_codes=("inr", "pt", "aptt", "fibrinogen", "d_dimer"),
    patterns_ru=("коагуляционный риск", "антикоагулянтный контекст", "повышенный D-димер — интерпретация с клиникой"),
    risk_rules=(_r("coag_abnormal", "клинически значимые отклонения ПТИ/МНО/Д-димера", RISK_HIGH),),
    next_steps_ru=("очная оценка", "срочная помощь при подозрении на ТЭЛА/кровотечение"),
)

MATRIX_REPRODUCTIVE = ProfileMatrixEntry(
    profile_key="reproductive_hormones_panel",
    priority=2,
    title_ru="Репродуктивные гормоны",
    marker_codes=("fsh", "lh", "estradiol", "progesterone", "prolactin", "testosterone", "shbg"),
    patterns_ru=("овуляторный/менструальный контекст", "гиперпролактинемия", "андрогенный профиль"),
    risk_rules=(_r("rep_context", "риск строго контекстный (возраст, цикл, терапия)", RISK_CONTEXTUAL),),
    next_steps_ru=("гинеколог/андролог", "повтор в нужной фазе цикла"),
)

MATRIX_ADRENAL = ProfileMatrixEntry(
    profile_key="adrenal_panel",
    priority=2,
    title_ru="Надпочечники / стресс-ось",
    marker_codes=("cortisol", "acth", "dheas"),
    patterns_ru=("базовый кортизол/АКТГ", "контекст стресса — только с клиникой"),
    risk_rules=(_r("adr_context", "интерпретация контекстная", RISK_CONTEXTUAL),),
    next_steps_ru=("эндокринолог", "повтор с учётом сбора крови"),
)


def _p3_stub(key: str, title: str, markers: Tuple[str, ...], patterns: Tuple[str, ...]) -> ProfileMatrixEntry:
    return ProfileMatrixEntry(
        profile_key=key,
        priority=3,
        title_ru=title,
        marker_codes=markers,
        patterns_ru=patterns,
        risk_rules=(_r(f"{key}_niche", "нишевый профиль — интерпретация врачом", RISK_CONTEXTUAL),),
        next_steps_ru=("очная интерпретация специалистом",),
        engine_notes_ru="Внедрять после стабилизации P0–P2.",
    )


PROFILE_MATRIX: Dict[str, ProfileMatrixEntry] = {
    MATRIX_CBC.profile_key: MATRIX_CBC,
    "cbc_with_reticulocytes": ProfileMatrixEntry(
        profile_key="cbc_with_reticulocytes",
        priority=0,
        title_ru="ОАК с ретикулоцитами",
        marker_codes=MATRIX_CBC.marker_codes + ("reticulocytes",),
        patterns_ru=MATRIX_CBC.patterns_ru + ("регенерация / гипопролиферация (ретикулоциты)",),
        risk_rules=MATRIX_CBC.risk_rules,
        next_steps_ru=MATRIX_CBC.next_steps_ru,
        engine_notes_ru="Наследует логику CBC + ретикулоциты.",
    ),
    MATRIX_URINALYSIS.profile_key: MATRIX_URINALYSIS,
    MATRIX_BIOCHEMISTRY.profile_key: MATRIX_BIOCHEMISTRY,
    MATRIX_LIPID.profile_key: MATRIX_LIPID,
    MATRIX_GLUCOSE.profile_key: MATRIX_GLUCOSE,
    MATRIX_IRON.profile_key: MATRIX_IRON,
    MATRIX_THYROID.profile_key: MATRIX_THYROID,
    MATRIX_LIVER.profile_key: MATRIX_LIVER,
    MATRIX_KIDNEY.profile_key: MATRIX_KIDNEY,
    MATRIX_INFLAMMATION.profile_key: MATRIX_INFLAMMATION,
    MATRIX_B12_FOLATE.profile_key: MATRIX_B12_FOLATE,
    MATRIX_VITAMIN_MINERAL.profile_key: MATRIX_VITAMIN_MINERAL,
    MATRIX_COAGULATION.profile_key: MATRIX_COAGULATION,
    MATRIX_REPRODUCTIVE.profile_key: MATRIX_REPRODUCTIVE,
    MATRIX_ADRENAL.profile_key: MATRIX_ADRENAL,
    "organic_acids_urine": _p3_stub(
        "organic_acids_urine",
        "Органические кислоты мочи",
        ("organic_acids_panel",),
        ("метаболические сигналы",),
    ),
    "amino_acids_panel": _p3_stub("amino_acids_panel", "Аминокислоты", ("amino_acids",), ("метаболом",)),
    "autoimmune_panel": _p3_stub("autoimmune_panel", "Аутоиммунные маркеры", ("ana", "ena", "rf"), ("аутоиммунный контекст",)),
    "infectious_serology_panel": _p3_stub(
        "infectious_serology_panel",
        "Инфекционная серология",
        ("serology",),
        ("серологические ответы",),
    ),
    "oncology_markers_panel": _p3_stub(
        "oncology_markers_panel",
        "Онкомаркеры",
        ("tumor_markers",),
        ("только с врачом, не для скрининга самостоятельно",),
    ),
    "generic_lab": ProfileMatrixEntry(
        profile_key="generic_lab",
        priority=3,
        title_ru="Общий лабораторный документ",
        marker_codes=(),
        patterns_ru=("тип анализа не классифицирован",),
        risk_rules=(_r("gen_unknown", "риск не оценивается", RISK_CONTEXTUAL),),
        next_steps_ru=("показать результаты врачу",),
    ),
}


def get_matrix_entry(profile_key: str) -> Optional[ProfileMatrixEntry]:
    """Вернуть строку матрицы или None."""
    return PROFILE_MATRIX.get(profile_key)


def matrix_keys() -> FrozenSet[str]:
    return frozenset(PROFILE_MATRIX.keys())


def validate_matrix_against_catalog() -> Tuple[bool, Tuple[str, ...]]:
    """
    Проверка: каждый ключ матрицы есть в PROFILE_CATALOG.
    Возвращает (ok, missing_in_catalog).
    """
    from app.services.clinical_engine.profile_catalog import PROFILE_CATALOG

    missing = tuple(sorted(k for k in PROFILE_MATRIX if k not in PROFILE_CATALOG))
    return (len(missing) == 0, missing)
