from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.services.lab_postprocess import postprocess_lab_analysis_for_user
from app.knowledge.filters.diagnosis_filter import is_relevant_diagnosis


@dataclass
class RankedDisease:
    code: str
    name: str
    score: float
    confidence: str


@dataclass
class DiseaseRule:
    id: str
    label_ru: str
    positive: Dict[str, int] = field(default_factory=dict)
    negative: Dict[str, int] = field(default_factory=dict)
    red_flags: List[str] = field(default_factory=list)


@dataclass
class RankedHypothesis:
    id: str
    label_ru: str
    score: float
    raw_score: int
    matched: List[str]


class DiagnosticRankingEngine:
    def __init__(self, rules: List[DiseaseRule]):
        self.rules = rules

    def rank(self, evidence_present: List[str], evidence_absent: List[str]) -> List[RankedHypothesis]:
        pset = set(evidence_present or [])
        aset = set(evidence_absent or [])
        results: List[RankedHypothesis] = []
        for rule in self.rules:
            score = 0
            matched: List[str] = []
            for key, weight in (rule.positive or {}).items():
                if key in pset:
                    score += int(weight)
                    matched.append(key)
            for key, weight in (rule.negative or {}).items():
                if key in pset:
                    score += int(weight)
                    matched.append("contra:" + key)
            for key, weight in (rule.positive or {}).items():
                if key in aset:
                    score -= max(1, int(weight) // 2)
            results.append(
                RankedHypothesis(
                    id=rule.id,
                    label_ru=rule.label_ru,
                    score=self._normalize(score),
                    raw_score=int(score),
                    matched=matched,
                )
            )
        results.sort(key=lambda x: x.score, reverse=True)
        return results

    @staticmethod
    def _normalize(score: int) -> float:
        if score <= 0:
            return 0.0
        if score >= 15:
            return 0.95
        return round(score / 15, 2)


_KNEE_RULES: list[dict[str, Any]] = [
    {
        "code": "knee_meniscus_injury",
        "name": "Подозрение на повреждение мениска",
        "required_any": ["knee_pain"],
        "weights": {
            "fall_impact": 4.0,
            "knee_pain": 2.0,
            "hard_flexion": 3.0,
            "hard_extension": 2.0,
            "locking_knee": 5.0,
            "click_knee": 2.0,
            "swelling_knee": 3.0,
        },
        "negative_weights": {"no_trauma": -3.0},
        "followups": [
            "Есть ли ощущение щелчка или блокировки в суставе?",
            "Можете полностью разогнуть и согнуть ногу?",
            "Больно ли наступать на ногу?",
        ],
        "safe_actions": [
            "Покой и ограничение нагрузки на 24-48 часов.",
            "Холод на колено 15-20 минут 3-4 раза в день.",
            "Держать ногу слегка приподнятой.",
        ],
        "suggested_tests": ["Рентген колена", "МРТ коленного сустава по показаниям"],
    },
    {
        "code": "knee_ligament_sprain",
        "name": "Растяжение связок колена",
        "required_any": ["knee_pain"],
        "weights": {
            "fall_impact": 3.5,
            "knee_pain": 2.0,
            "hard_flexion": 2.0,
            "swelling_knee": 3.0,
            "cannot_bear_weight": 3.0,
        },
        "negative_weights": {"no_trauma": -2.0},
        "followups": [
            "Больно ли наступать на ногу?",
            "Есть ли отек вокруг колена?",
            "Была ли нестабильность в суставе при ходьбе?",
        ],
        "safe_actions": [
            "Покой, холод и эластичная фиксация.",
            "Избегать бега и прыжков до уменьшения боли.",
        ],
        "suggested_tests": ["Рентген колена", "УЗИ мягких тканей по показаниям"],
    },
    {
        "code": "knee_contusion",
        "name": "Ушиб коленного сустава",
        "required_any": ["knee_pain"],
        "weights": {
            "fall_impact": 3.0,
            "knee_pain": 2.0,
            "swelling_knee": 2.0,
            "after_training": 1.0,
        },
        "negative_weights": {"locking_knee": -1.5},
        "followups": [
            "Есть ли синяк или локальная припухлость?",
            "Нарастает ли боль при ходьбе?",
        ],
        "safe_actions": [
            "Холод на область ушиба в первые сутки.",
            "Щадящий режим и постепенное возвращение нагрузки.",
        ],
        "suggested_tests": ["Рентген при сильной боли/подозрении на костную травму"],
    },
    {
        "code": "knee_hemarthrosis_possible",
        "name": "Подозрение на гемартроз (кровь в суставе)",
        "required_any": ["knee_pain"],
        "weights": {
            "fall_impact": 3.0,
            "knee_pain": 2.0,
            "swelling_knee": 4.0,
            "cannot_bear_weight": 3.0,
        },
        "negative_weights": {"no_trauma": -2.0},
        "followups": [
            "Отек появился быстро в первые часы после травмы?",
            "Можно ли опереться на ногу?",
        ],
        "safe_actions": [
            "Не нагружать ногу до очной оценки.",
            "Холод и приподнятое положение конечности.",
        ],
        "suggested_tests": ["Срочная травматологическая оценка", "УЗИ/рентген, при необходимости пункция"],
    },
    {
        "code": "knee_overuse_pain",
        "name": "Перегрузочная боль колена после нагрузки",
        "required_any": ["knee_pain"],
        "weights": {
            "after_training": 2.0,
            "knee_pain": 2.0,
            "no_trauma": 4.0,
        },
        "negative_weights": {
            "fall_impact": -3.0,
            "locking_knee": -2.0,
            "cannot_bear_weight": -2.0,
        },
        "followups": [
            "Боль появилась постепенно или сразу после травмы?",
            "Есть ли отек или только боль после нагрузки?",
        ],
        "safe_actions": [
            "Снизить нагрузку на 5-7 дней.",
            "Добавить мягкую разминку и восстановление.",
        ],
        "suggested_tests": ["Очная консультация при сохранении боли >7-10 дней"],
    },
]

_ANKLE_RULES: list[dict[str, Any]] = [
    {
        "code": "ankle_ligament_sprain",
        "name": "Растяжение связок голеностопа",
        "required_any": ["ankle_pain"],
        "weights": {
            "ankle_pain": 3.0,
            "fall_impact": 2.0,
            "twisting_motion": 5.0,
            "swelling_ankle": 3.0,
            "cannot_bear_weight": 3.0,
        },
        "negative_weights": {"no_trauma": -2.0},
        "followups": [
            "Был ли подворачивающий механизм (подвернули стопу)?",
            "Есть ли выраженный отек голеностопа?",
            "Можете ли вы наступать на ногу?",
        ],
        "safe_actions": [
            "Покой, холод и фиксация голеностопа.",
            "Избегать нагрузки до уменьшения боли.",
        ],
        "suggested_tests": ["Рентген голеностопа по Ottawa rules", "Очный осмотр травматолога"],
    },
    {
        "code": "ankle_contusion",
        "name": "Ушиб голеностопа",
        "required_any": ["ankle_pain"],
        "weights": {"ankle_pain": 2.0, "direct_blow": 3.0, "swelling_ankle": 2.0},
        "negative_weights": {"twisting_motion": -1.0},
        "followups": [
            "Есть ли локальный синяк или припухлость?",
            "Боль уменьшается в покое?",
        ],
        "safe_actions": [
            "Холод в первые сутки.",
            "Щадящая нагрузка и постепенное восстановление.",
        ],
        "suggested_tests": ["Рентген при стойкой боли/невозможности опоры"],
    },
]

_SHOULDER_RULES: list[dict[str, Any]] = [
    {
        "code": "shoulder_rotator_cuff_strain",
        "name": "Перегрузка/повреждение вращательной манжеты плеча",
        "required_any": ["shoulder_pain"],
        "weights": {
            "shoulder_pain": 3.0,
            "recent_exercise": 2.0,
            "pain_on_abduction": 4.0,
            "night_pain_shoulder": 2.0,
        },
        "negative_weights": {"no_trauma": -1.0},
        "followups": [
            "Больно ли поднимать руку в сторону или вверх?",
            "Есть ли боль ночью на этой стороне?",
            "Была ли травма плеча/падение?",
        ],
        "safe_actions": [
            "Снизить нагрузку на плечо.",
            "Лед/тепло по переносимости, без движений через резкую боль.",
        ],
        "suggested_tests": ["Очный осмотр ортопеда", "УЗИ/МРТ плеча по показаниям"],
    },
    {
        "code": "shoulder_contusion_or_sprain",
        "name": "Ушиб/растяжение плечевого сустава",
        "required_any": ["shoulder_pain"],
        "weights": {"shoulder_pain": 2.0, "fall_impact": 3.0, "direct_blow": 3.0},
        "negative_weights": {"no_trauma": -2.0},
        "followups": [
            "Была ли деформация, резкий щелчок или ограничение движений?",
            "Можете ли держать руку без резкой боли?",
        ],
        "safe_actions": [
            "Покой для плеча 24-48 часов.",
            "Холод на область боли.",
        ],
        "suggested_tests": ["Рентген плеча при травме", "Очный травматолог по показаниям"],
    },
]

_BACK_RULES: list[dict[str, Any]] = [
    {
        "code": "back_muscle_spasm",
        "name": "Мышечно-тоническая боль спины",
        "required_any": ["back_pain"],
        "weights": {"back_pain": 3.0, "recent_exercise": 1.0, "cold_exposure": 2.0, "no_trauma": 2.0},
        "negative_weights": {"neurologic_deficit": -5.0, "cannot_bear_weight": -2.0},
        "followups": [
            "Есть ли онемение, слабость в ноге или прострел в ногу?",
            "Была ли травма/падение?",
            "Есть ли температура на фоне боли?",
        ],
        "safe_actions": [
            "Щадящий режим и избегать резких движений.",
            "Сухое тепло и мягкая мобилизация без усиления боли.",
        ],
        "suggested_tests": ["Очный осмотр при сохранении боли >3-5 дней"],
    },
    {
        "code": "back_disc_radicular_suspected",
        "name": "Подозрение на дискогенную/радикулярную боль",
        "required_any": ["back_pain"],
        "weights": {"back_pain": 2.0, "radicular_pain": 4.0, "neurologic_deficit": 4.0},
        "negative_weights": {"no_trauma": -1.0},
        "followups": [
            "Отдает ли боль в ногу ниже колена?",
            "Есть ли слабость или онемение?",
            "Есть ли нарушения мочеиспускания/дефекации?",
        ],
        "safe_actions": [
            "Не поднимать тяжести и не делать резких наклонов.",
            "Очная консультация невролога/травматолога.",
        ],
        "suggested_tests": ["МРТ поясничного отдела по показаниям", "Неврологический осмотр"],
    },
]

_ORAL_RULES: list[dict[str, Any]] = [
    {
        "code": "oral_dental_abscess_suspected",
        "name": "Подозрение на абсцесс зуба/десны",
        "required_any": ["tooth_pain", "gum_swelling"],
        "weights": {
            "tooth_pain": 2.0,
            "gum_swelling": 3.0,
            "facial_swelling": 4.0,
            "fever_with_dental_pain": 4.0,
            "pus_mentioned": 3.0,
        },
        "negative_weights": {
            "sore_throat": -5.0,
            "runny_nose": -4.0,
            "cough": -3.0,
            "sputum": -3.0,
        },
        "followups": [
            "Есть ли отёк десны или щеки?",
            "Есть ли температура?",
            "Больно ли глотать?",
            "Есть ли гной или неприятный привкус?",
        ],
        "safe_actions": [
            "Обратиться к стоматологу в ближайшее время.",
            "До осмотра: полоскание тёплой водой, избегать давления на область.",
        ],
        "suggested_tests": ["Очный осмотр стоматолога"],
    },
    {
        "code": "oral_tooth_sensitivity",
        "name": "Чувствительность зуба (горячее/холодное)",
        "required_any": ["tooth_pain"],
        "weights": {"tooth_pain": 3.0},
        "negative_weights": {"facial_swelling": -2.0, "fever_with_dental_pain": -3.0},
        "followups": [
            "Боль постоянная или только на горячее/холодное?",
            "Есть ли отёк десны или щеки?",
        ],
        "safe_actions": [
            "Избегать температурных раздражителей.",
            "Обратиться к стоматологу для осмотра.",
        ],
        "suggested_tests": ["Осмотр стоматолога"],
    },
    {
        "code": "oral_gum_disease",
        "name": "Заболевание дёсен (гингивит/кровоточивость)",
        "required_any": ["gum_bleeding", "gum_swelling"],
        "weights": {"gum_bleeding": 3.0, "gum_swelling": 2.0, "bad_breath": 1.0},
        "negative_weights": {"facial_swelling": -1.0},
        "followups": [
            "Как давно кровоточат дёсны?",
            "Есть ли отёк или боль?",
        ],
        "safe_actions": [
            "Мягкая гигиена полости рта, полоскания.",
            "Очный осмотр стоматолога для оценки.",
        ],
        "suggested_tests": ["Осмотр стоматолога"],
    },
    {
        "code": "oral_aphthous_ulcer",
        "name": "Афтозная язва / стоматит",
        "required_any": ["mouth_ulcer", "multiple_mouth_ulcers"],
        "weights": {"mouth_ulcer": 3.0, "multiple_mouth_ulcers": 2.0, "tongue_pain": 1.0},
        "negative_weights": {},
        "followups": [
            "Одна язвочка или несколько?",
            "Есть ли температура или затруднение глотания?",
        ],
        "safe_actions": [
            "Избегать раздражающей пищи, мягкая гигиена.",
            "При сохранении или ухудшении — осмотр врача.",
        ],
        "suggested_tests": ["Осмотр при длительном течении"],
    },
    {
        "code": "oral_candidiasis",
        "name": "Кандидоз полости рта",
        "required_any": ["oral_white_patch", "tongue_pain"],
        "weights": {"oral_white_patch": 4.0, "tongue_pain": 2.0, "dry_mouth": 1.0},
        "negative_weights": {},
        "followups": [
            "Есть ли белый налёт, который снимается?",
            "Принимали ли недавно антибиотики или ингаляционные кортикостероиды?",
        ],
        "safe_actions": [
            "Обратиться к врачу/стоматологу для подтверждения и назначения лечения.",
        ],
        "suggested_tests": ["Осмотр, при необходимости мазок"],
    },
    {
        "code": "oral_post_extraction",
        "name": "Состояние после удаления зуба",
        "required_any": ["post_dental_extraction"],
        "weights": {
            "post_dental_extraction": 3.0,
            "facial_swelling": 2.0,
            "fever_with_dental_pain": 3.0,
        },
        "negative_weights": {},
        "followups": [
            "Есть ли нарастающий отёк или температура?",
            "Останавливается ли кровотечение из лунки?",
        ],
        "safe_actions": [
            "Следовать рекомендациям стоматолога после удаления.",
            "При нарастающем отёке, температуре или кровотечении — срочно к врачу.",
        ],
        "suggested_tests": ["Повторный осмотр стоматолога при ухудшении"],
    },
    {
        "code": "oral_tmj_jaw",
        "name": "Боль в челюсти / ВНЧС",
        "required_any": ["jaw_pain"],
        "weights": {"jaw_pain": 3.0, "tooth_pain": 1.0},
        "negative_weights": {},
        "followups": [
            "Боль при жевании или при открывании рта?",
            "Есть ли щелчки при движении челюсти?",
        ],
        "safe_actions": [
            "Щадящая нагрузка на челюсть, мягкая пища.",
            "Очный осмотр стоматолога/челюстно-лицевого хирурга при необходимости.",
        ],
        "suggested_tests": ["Осмотр при стойкой боли"],
    },
]

_ALL_RULES: list[dict[str, Any]] = (
    _KNEE_RULES + _ANKLE_RULES + _SHOULDER_RULES + _BACK_RULES + _ORAL_RULES
)

# Universal scoring for recalculate_from_case_state (stage1 simple pipeline)
DISEASE_RULES: dict[str, dict[str, Any]] = {
    "knee_overuse": {"positive": {"knee_pain": 2, "recent_exercise": 2}, "negative": {"knee_trauma": -3}},
    "knee_contusion": {"positive": {"knee_pain": 2, "knee_trauma": 3}, "negative": {}},
    "dental_abscess": {"positive": {"tooth_pain": 2, "gum_swelling": 3, "facial_swelling": 3}, "negative": {}},
    "pulpitis": {"positive": {"tooth_pain": 3}, "negative": {"facial_swelling": -2}},
    "periodontitis": {"positive": {"gum_swelling": 2, "gum_bleeding": 2}, "negative": {}},
    "oral_aphthous": {"positive": {"mouth_ulcer": 3}, "negative": {}},
}

_RED_FLAG_FEATURES = {
    "cannot_bear_weight": "невозможно наступить на ногу",
    "gross_deformity": "деформация сустава/конечности",
    "severe_swelling_knee": "сильный отек сустава после травмы",
    "hot_swollen_joint_with_fever": "горячий отечный сустав с температурой",
    "neurologic_deficit": "неврологический дефицит на фоне боли в спине",
}


def normalize(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower().replace("ё", "е"))


def detect_profile(symptoms: Any) -> str:
    t = normalize(symptoms)
    if any(k in t for k in ("зуб", "десн", "полость рта", "язвочк", "язык", "челюст", "запах изо рта", "флюс", "удален зуб")):
        return "oral_cavity"
    if any(k in t for k in ("колен", "сустав", "связк", "мениск", "растяж")):
        return "msk"
    if any(k in t for k in ("голеностоп", "лодыж", "стоп", "плеч", "спин", "поясниц", "шея")):
        return "msk"
    if any(k in t for k in ("живот", "тошнот", "рвот", "понос", "диаре")):
            return "gastro"
    return "general"


def _extract_features(text: str) -> set[str]:
    t = normalize(text)
    f: set[str] = set()
    if "колен" in t:
        f.add("knee_pain")
    if any(k in t for k in ("после трен", "бег", "бежал", "нагрузк")):
        f.add("after_training")
        f.add("recent_exercise")
    if any(k in t for k in ("упал", "паден", "удар", "ушиб", "травм")):
        f.add("fall_impact")
    if any(k in t for k in ("трудно сгиб", "не могу согнуть", "больно сгиб")):
        f.add("hard_flexion")
    if any(k in t for k in ("трудно разог", "не могу разогнуть", "больно разог")):
        f.add("hard_extension")
    if any(k in t for k in ("заклини", "блокиров", "не двигается")):
        f.add("locking_knee")
    if any(k in t for k in ("щелч", "хруст")):
        f.add("click_knee")
    if any(k in t for k in ("отек", "опух", "припух")):
        f.add("swelling_knee")
    if any(k in t for k in ("сильный отек", "резко опух", "очень опух")):
        f.add("severe_swelling_knee")
    if any(k in t for k in ("не могу наступить", "невозможно наступить", "не опираюсь")):
        f.add("cannot_bear_weight")
    if any(k in t for k in ("деформац", "криво стоит")):
        f.add("deformity_knee")
    if any(k in t for k in ("температур", "лихорад")):
        f.add("fever")
    if any(k in t for k in ("голеностоп", "лодыж", "стоп")):
        f.add("ankle_pain")
    if any(k in t for k in ("подвернул", "скрутил стопу", "неловко наступил", "подворачив")):
        f.add("twisting_motion")
    if any(k in t for k in ("опухла лодыжка", "отек лодыжки", "голеностоп опух")):
        f.add("swelling_ankle")
    if any(k in t for k in ("плеч", "плечо")):
        f.add("shoulder_pain")
    if any(k in t for k in ("больно поднимать руку", "боль при отведении", "не могу поднять руку")):
        f.add("pain_on_abduction")
    if any(k in t for k in ("ночью болит плечо", "ночная боль в плече")):
        f.add("night_pain_shoulder")
    if any(k in t for k in ("болит спина", "боль в спине", "поясниц", "прострел", "шея болит")):
        f.add("back_pain")
    if any(k in t for k in ("продуло", "просквоз", "сквозняк", "замерз", "замерзла спина")):
        f.add("cold_exposure")
    if any(k in t for k in ("отдает в ногу", "отдаёт в ногу", "по ноге тянет", "прострел в ногу")):
        f.add("radicular_pain")
    if any(k in t for k in ("онемение", "слабость в ноге", "провисает стопа", "нарушение мочеиспускания")):
        f.add("neurologic_deficit")
    if "knee_pain" in f and not any(k in t for k in ("упал", "паден", "удар", "травм", "ушиб")):
        f.add("no_trauma")
    if any(x in f for x in ("ankle_pain", "shoulder_pain", "back_pain")) and not any(k in t for k in ("упал", "паден", "удар", "травм", "ушиб", "подвернул", "скрутил")):
        f.add("no_trauma")
    # Oral
    if any(k in t for k in ("зуб", "зубн", "болит зуб")):
        f.add("tooth_pain")
    if any(k in t for k in ("десн", "дёсен", "опухл десн", "отек десн")):
        f.add("gum_swelling")
    if any(k in t for k in ("кровоточ", "кровь из десен")):
        f.add("gum_bleeding")
    if any(k in t for k in ("язвочк", "язв во рту", "афт")):
        f.add("mouth_ulcer")
    if any(k in t for k in ("белый налет", "белое пятно", "налёт во рту")):
        f.add("oral_white_patch")
    if any(k in t for k in ("жжёт язык", "болит язык")):
        f.add("tongue_pain")
    if any(k in t for k in ("челюст", "внчс", "болит челюсть")):
        f.add("jaw_pain")
    if any(k in t for k in ("неприятный запах", "запах изо рта")):
        f.add("bad_breath")
    if any(k in t for k in ("сухость во рту", "сухо во рту")):
        f.add("dry_mouth")
    if any(k in t for k in ("трудно глотать", "затруднение глотания", "больно глотать")):
        f.add("trouble_swallowing")
    if any(k in t for k in ("отек щек", "отёк щеки", "флюс", "опухла щека", "отек лица")):
        f.add("facial_swelling")
    if any(k in t for k in ("удален зуб", "удалили зуб", "после удаления", "вырвали зуб")):
        f.add("post_dental_extraction")
    if any(k in t for k in ("температур", "лихорад")) and any(k in t for k in ("зуб", "десн", "флюс")):
        f.add("fever_with_dental_pain")
    if any(k in t for k in ("гной", "гнойник", "абсцесс")):
        f.add("pus_mentioned")
    if any(k in t for k in ("трудно открыть рот", "тризм")):
        f.add("trismus_like")
    return f


def recalculate_scores(features: set[str], candidate_rules: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    rules = candidate_rules or _ALL_RULES
    scored: list[dict[str, Any]] = []
    for rule in rules:
        required_any = {str(x).strip() for x in (rule.get("required_any") or []) if str(x).strip()}
        if required_any and not (required_any & set(features)):
            continue
        score = 0.0
        for key, w in (rule.get("weights") or {}).items():
            if key in features:
                score += float(w)
        for key, w in (rule.get("negative_weights") or {}).items():
            if key in features:
                score += float(w)
        scored.append(
            {
                "code": str(rule.get("code") or "").strip(),
                "name": str(rule.get("name") or "").strip(),
                "score": round(score, 3),
                "followups": [str(x).strip() for x in (rule.get("followups") or []) if str(x).strip()],
                "safe_actions": [str(x).strip() for x in (rule.get("safe_actions") or []) if str(x).strip()],
                "suggested_tests": [str(x).strip() for x in (rule.get("suggested_tests") or []) if str(x).strip()],
            }
        )
    scored.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    max_score = max([float(x.get("score") or 0.0) for x in scored] or [1.0])
    for item in scored:
        score = float(item.get("score") or 0.0)
        item["confidence"] = round(max(0.05, min(0.95, score / max_score if max_score > 0 else 0.05)), 2)
        item.setdefault("label_ru", item.get("name") or "")
    return scored


def rank_differential(
    evidence_present: list[str] | set[str],
    evidence_absent: list[str] | set[str] | None = None,
    evidence_unknown: list[str] | set[str] | None = None,
) -> list[dict[str, Any]]:
    """Rank hypotheses by evidence; optional absent/unknown do not change score, only filter."""
    present = set(evidence_present or [])
    return recalculate_scores(present, _ALL_RULES)


def recalculate_from_case_state(case_state: dict[str, Any]) -> list[dict[str, Any]]:
    """Universal recalc: evidence_present vs DISEASE_RULES (positive/negative). Returns list of {id, score, matched}."""
    evidence = list(case_state.get("evidence_present", []))
    results: list[dict[str, Any]] = []
    for disease, rule in DISEASE_RULES.items():
        score = 0
        matched: list[str] = []
        for key, weight in rule.get("positive", {}).items():
            if key in evidence:
                score += weight
                matched.append(key)
        for key, weight in rule.get("negative", {}).items():
            if key in evidence:
                score += weight
                matched.append(key)
        if score <= 0:
            continue
        results.append({"id": disease, "score": score, "matched": matched})
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:5]


def recalculate_from_case_state_full(case_state: dict[str, Any]) -> list[dict[str, Any]]:
    """Recompute top hypotheses from case_state evidence_present (full format with code, name, followups)."""
    present = set(case_state.get("evidence_present") or [])
    return recalculate_scores(present, _ALL_RULES)


def prune_low_confidence(
    items: list[dict[str, Any]],
    threshold: float = 0.15,
) -> list[dict[str, Any]]:
    """Drop hypotheses below confidence threshold; keep at least top 1 if any."""
    if not items:
        return []
    out = [x for x in items if float(x.get("confidence") or x.get("score") or 0) >= threshold]
    return out if out else items[:1]


def remove_low_probability(scored_hypotheses: list[dict[str, Any]], min_score: float = 1.5) -> list[dict[str, Any]]:
    out = [x for x in (scored_hypotheses or []) if float(x.get("score") or 0.0) >= float(min_score)]
    return out if out else (scored_hypotheses[:2] if scored_hypotheses else [])


def update_hypothesis(current_state: dict[str, Any] | None, new_text: str) -> dict[str, Any]:
    previous = current_state or {}
    prev_features = set(previous.get("features") or [])
    new_features = _extract_features(new_text)
    if {"fall_impact", "direct_blow", "knee_trauma"} & prev_features:
        new_features.discard("no_trauma")
    all_features = prev_features | new_features
    if {"fall_impact", "direct_blow", "knee_trauma"} & all_features:
        all_features.discard("no_trauma")
    ranked = recalculate_scores(all_features, _ALL_RULES)
    top = remove_low_probability(ranked, min_score=1.5)
    followups: list[str] = []
    safe_actions: list[str] = []
    tests: list[str] = []
    for item in top[:3]:
        followups.extend(item.get("followups") or [])
        safe_actions.extend(item.get("safe_actions") or [])
        tests.extend(item.get("suggested_tests") or [])
    red_flags = [label for feat, label in _RED_FLAG_FEATURES.items() if feat in all_features]
    return {
        "features": sorted(all_features),
        "hypotheses": top[:5],
        "followup_questions": list(dict.fromkeys(followups))[:5],
        "safe_actions": list(dict.fromkeys(safe_actions))[:5],
        "suggested_tests": list(dict.fromkeys(tests))[:5],
        "red_flags": red_flags,
    }


def triage(symptoms: Any):
    state = update_hypothesis({}, str(symptoms or ""))
    if state.get("red_flags"):
            return {
                "triage": "urgent",
            "reason": "обнаружены признаки потенциально опасной травмы",
            "red_flags": state.get("red_flags") or [],
            }
    return {
        "triage": "routine",
        "reason": "нет явных признаков экстренной травмы",
        "red_flags": [],
    }


def confidence(score: float) -> str:
    if score >= 7:
        return "high"
    if score >= 4:
        return "medium"
    if score >= 1.5:
        return "low"
    return "very_low"


def rank_diseases(symptom_context: Any, nutrition_context: Any, top_k: int = 5) -> List[RankedDisease]:
    merged = normalize(symptom_context) + " " + normalize(nutrition_context)
    state = update_hypothesis({}, merged)
    out: list[RankedDisease] = []
    for h in (state.get("hypotheses") or [])[:top_k]:
        sc = float(h.get("score") or 0.0)
        out.append(
            RankedDisease(
                code=str(h.get("code") or ""),
                name=str(h.get("name") or ""),
                score=sc,
                confidence=confidence(sc),
            )
        )
    return out


def build_diagnostic_assessment(
        symptom_context: Any,
        nutrition_context: Any = None,
    lab_context: Dict | None = None,
    top_k: int = 5,
):
    merged = normalize(symptom_context) + " " + normalize(nutrition_context)
    ranked = rank_diseases(symptom_context=merged, nutrition_context="", top_k=top_k)
    triage_data = triage(merged)
    return {
        "clinical_profile": detect_profile(merged),
        "ranked_diseases": [
            {
                "code": r.code,
                "name": r.name,
                "score": r.score,
                "confidence": r.confidence,
            }
            for r in ranked
        ],
        "triage": triage_data,
    }


def filter_ranked_hypotheses_for_labs_only(
    hypotheses: list[dict[str, Any]],
    symptoms: list[str] | None = None,
    lab_type: str | None = None,
) -> list[dict[str, Any]]:
    """Жёсткий фильтр гипотез до выдачи пользователю: стоп-лист, порог вероятности, без экзотики без симптомов.
    lab_type: organic_acids, cbc, thyroid, unknown — для BLOCK_BY_LAB_TYPE.
    Использует app.knowledge.filters.diagnosis_filter.is_relevant_diagnosis.
    """
    symptoms_list = list(symptoms or [])
    context = {"symptoms": symptoms_list, "lab_type": lab_type}
    filtered = [
        h
        for h in (hypotheses or [])
        if is_relevant_diagnosis(
            h.get("name") or h.get("title"),
            float(h.get("probability") or h.get("score") or 0),
            context,
        )
    ]
    # Максимум 1–2 гипотезы для organic acids
    max_hyp = 2 if lab_type == "organic_acids" else 3
    return filtered[:max_hyp]