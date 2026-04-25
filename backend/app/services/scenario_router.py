from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.scenario_pack_loader import ScenarioPack, load_all_scenario_packs

try:
    from app.services import input_normalizer
except Exception:
    input_normalizer = None
try:
    from app.services.anatomy_router import detect_ortho_zone
except Exception:
    detect_ortho_zone = None

_APP_DIR = Path(__file__).resolve().parent.parent
_RANKING_CALIBRATION_PATH = _APP_DIR / "knowledge" / "scenario_ranking_calibration.json"

_DEFAULT_RANKING_CALIBRATION: dict[str, Any] = {
    "branch_bonus": {
        "default": 0.15,
        "women_health": 0.45,
        "pediatric": 0.45,
        "ent": 0.35,
    },
    "context_weights": {
        "pediatric_match_boost": 0.75,
        "women_health_match_boost": 0.75,
        "ent_match_boost": 0.55,
        "women_health_when_pediatric_penalty": -0.15,
        "pediatric_when_women_health_penalty": -0.15,
        "resp_or_oral_when_ent_penalty": -0.10,
    },
}


@lru_cache(maxsize=1)
def get_scenario_ranking_calibration() -> dict[str, Any]:
    calibration = dict(_DEFAULT_RANKING_CALIBRATION)
    if _RANKING_CALIBRATION_PATH.exists():
        try:
            payload = json.loads(_RANKING_CALIBRATION_PATH.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                calibration.update({k: v for k, v in payload.items() if isinstance(v, dict)})
        except Exception:
            pass
    return calibration


def _branch_bonus(branch: str) -> float:
    cfg = get_scenario_ranking_calibration()
    table = cfg.get("branch_bonus") if isinstance(cfg.get("branch_bonus"), dict) else {}
    default_value = float(table.get("default", 0.15))
    return float(table.get(branch, default_value))

_ALIAS_HINTS: dict[str, list[str]] = {
    "oral_cavity": ["зуб", "десн", "рот", "язык", "щека", "челюст", "налет", "язв", "глотать", "флюс"],
    "orthopedics": ["колено", "голеностоп", "спина", "плечо", "шея", "сустав", "травм", "упал", "подвернул"],
    "respiratory": ["каш", "горл", "насморк", "одыш", "температур", "ухо", "синус"],
    "gastro": ["живот", "тошн", "рвот", "стул", "изжог", "понос", "запор"],
    "cardio": ["сердц", "давлен", "груд", "пульс", "одыш"],
    "neuro": ["голов", "онем", "слабост", "судорог", "памят", "головокруж"],
    "allergy_skin": ["сып", "зуд", "аллерг", "крапив", "отек губ", "кожа"],
    "urinary": ["моч", "цистит", "поясниц", "позыв", "кровь в моче"],
    "fatigue_deficiency": ["слабост", "устал", "желез", "анем", "выпадение волос"],
    "women_health": ["месячн", "цикл", "беремен", "выделени", "таз", "послеродов", "лактац"],
    "pediatric": ["ребен", "ребён", "младен", "дет", "педиатр", "ночной плач", "школ"],
    "ent": ["ухо", "нос", "горл", "синус", "миндалин", "осипл", "шум в ушах"],
}

# -------- Aliases: разговорные фразы → id сценария (после нормализации текста) --------
SCENARIO_ALIASES: dict[str, list[str]] = {
    "orthopedics_knee_trauma": [
        "упал на колено",
        "ударил колено",
        "колено после падения",
        "трудно сгибать колено",
        "больно наступать после падения",
    ],
    "orthopedics_ankle_twist": [
        "подвернул ногу",
        "ногу подвернул",
        "щиколотка опухла",
        "голеностоп после подворачивания",
    ],
    "orthopedics_low_back_radicular": [
        "спину сорвал",
        "прострелило в спине",
        "отдает в ногу",
        "фигачит в ногу",
    ],
    "orthopedics_shoulder_instability": [
        "плечо как будто вылетает",
        "плечо вылетает",
        "нестабильность плеча",
    ],
    "oral_toothache_swelling": [
        "болит зуб и опухла десна",
        "зуб ноет и десна опухла",
        "десну раздуло",
        "щеку ведет",
        "флюс",
        "щека распухла от зуба",
        "отек щеки",
        "отек десны или щеки при зубной боли",
    ],
    "oral_post_extraction_complication": [
        "после удаления зуба стало хуже",
        "воняет после удаления зуба",
        "неприятный запах после удаления зуба",
        "после удаления болит сильнее",
    ],
    "oral_mouth_ulcer": [
        "язвочка во рту",
        "болячка во рту",
        "афта во рту",
    ],
    "oral_oral_thrush_like": [
        "белый налет во рту",
        "во рту белая хрень",
        "язык жжет и белый налет",
    ],
    "oral_gum_bleeding": [
        "кровоточат десны",
        "десны кровят",
    ],
    "respiratory_sore_throat_fever": [
        "болит горло и температура",
        "горло дерет и температура",
        "трудно глотать и температура",
    ],
    "respiratory_cough_fever": [
        "кашель и температура",
        "кашляю и температура",
        "сильный кашель и температура",
    ],
    "respiratory_cough_shortness_breath": [
        "кашель и тяжело дышать",
        "дышать не кайф и кашель",
        "кашляю и тяжело дышать",
    ],
    "respiratory_mild_uri": [
        "насморк и першит горло",
        "насморк и горло",
        "слегка болит горло и насморк",
    ],
    "gastro_abdominal_pain_after_food": [
        "живот болит после еды",
        "после еды болит живот",
        "живот мутит после еды",
        "после жирного хуже",
    ],
    "gastro_vomiting_dehydration": [
        "меня полощет",
        "рвота весь день",
        "рвота с утра",
        "рвота",
        "вода назад",
        "не могу пить после рвоты",
    ],
    "gastro_rlq_pain": [
        "справа внизу болит живот",
        "живот справа внизу",
        "боль справа внизу живота",
    ],
    "gastro_diarrhea": [
        "понос",
        "пронесло",
        "диарея со вчера",
    ],
    "cardio_palpitations": [
        "сердце колотит",
        "пульс лупит",
        "сильное сердцебиение",
    ],
    "cardio_chest_pressure": [
        "грудь давит",
        "сдавливает в груди",
        "давящая боль в груди",
    ],
    "cardio_exertional_chest_pain": [
        "при ходьбе в груди не нравится",
        "когда быстрее иду, в груди не нравится",
        "при нагрузке неприятно в груди",
        "дискомфорт в груди при нагрузке",
        "когда быстрее иду, дискомфорт в груди",
    ],
    "neuro_headache_red_flags": [
        "голова трещит",
        "голова раскалывается",
        "свет бесит",
        "сильная головная боль и температура",
    ],
    "neuro_arm_weakness": [
        "рука как не моя",
        "ватная рука",
        "слабость в руке",
        "немеет рука",
        "онемение или слабость руки",
    ],
    "neuro_dizziness": [
        "шатает",
        "кружит",
        "кружится голова и шатает",
    ],
    "urinary_dysuria_frequency": [
        "писать больно",
        "больно писать",
        "боль при мочеиспускании",
        "бегаю часто в туалет",
        "часто и больно мочиться",
    ],
    "urinary_upper_tract_concern": [
        "температура и поясница болит",
        "почки походу",
        "болит поясница и температура",
    ],
    "urinary_blood_or_abnormal_urine": [
        "моча странная",
        "кровь в моче",
        "моча необычная и больно",
    ],
    "fatigue_general": [
        "сил нет вообще",
        "как тряпка",
        "слабость постоянная",
    ],
    "fatigue_hair_nails": [
        "волосы лезут и ногти никакие",
        "выпадают волосы и ломкие ногти",
        "усталость и волосы лезут",
    ],
    "allergy_rash_itching": [
        "все чешется и высыпало",
        "сыпь и зуд",
        "чешется и сыпь",
    ],
    "allergy_urticaria_swelling": [
        "крапивой пошел",
        "крапивница и губа пухнет",
        "губа пухнет и сыпь",
    ],
    "allergy_skin_eczema_flare": [
        "обострение экземы",
        "экзема обострилась",
        "снова экзема и зуд",
    ],
    "allergy_skin_insect_bite_reaction": [
        "реакция на укус",
        "сильная реакция на укус насекомого",
        "после укуса отек и зуд",
    ],
    "cardio_fainting": [
        "обморок",
        "потерял сознание",
        "потеряла сознание",
        "чуть не упал в обморок",
    ],
    "women_health_heavy_period_bleeding": [
        "обильные месячные",
        "очень сильные месячные",
        "сильное кровотечение при месячных",
    ],
    "women_health_painful_periods": [
        "болезненные месячные",
        "сильная боль во время месячных",
    ],
    "women_health_vaginal_discharge": [
        "необычные выделения",
        "выделения с запахом",
    ],
    "women_health_pregnancy_bleeding_warning": [
        "кровянистые выделения при беременности",
        "кровит во время беременности",
    ],
    "women_health_vaginal_itching": [
        "зуд и жжение в интимной зоне",
        "интимный зуд и жжение",
        "жжение и зуд по женски",
    ],
    "women_health_pelvic_pain_fever": [
        "температура и боль внизу живота",
        "боль внизу живота и температура",
    ],
    "women_health_early_pregnancy_nausea": [
        "беременность 8 недель, сильная тошнота и рвота",
        "беременность и сильная тошнота с рвотой",
    ],
    "women_health_breast_pain_lactation": [
        "болит грудь при кормлении, есть уплотнение",
        "боль в груди при кормлении и уплотнение",
    ],
    "women_health_breast_lump_new": [
        "появилось новое уплотнение в груди",
        "новое уплотнение в груди",
    ],
    "pediatric_fever_child_no_focus": [
        "у ребенка температура",
        "у ребёнка температура без причины",
    ],
    "pediatric_rash_fever_child": [
        "у ребенка сыпь и температура",
        "сыпь и температура у ребенка",
    ],
    "pediatric_vomiting_child_dehydration": [
        "у ребенка рвота и не пьет",
        "ребенка рвет и мало пьет",
    ],
    "pediatric_sore_throat_child": [
        "у ребенка боль в горле и трудно глотать",
        "ребенку больно глотать и болит горло",
    ],
    "pediatric_constipation_child": [
        "у ребенка запор и боль при стуле",
        "запор у ребенка и больно в туалет",
    ],
    "pediatric_headache_child_red_flags": [
        "у ребенка головная боль и рвота",
        "головная боль и рвота у ребенка",
    ],
    "ent_ear_pain_swimmer": [
        "болит ухо после бассейна",
        "ухо болит после купания",
    ],
    "ent_sinusitis_purulent": [
        "гнойный насморк и боль в пазухах",
        "боль в пазухах и густые выделения",
    ],
    "ent_tonsillitis_exudate": [
        "налеты на миндалинах",
        "горло болит и налет на миндалинах",
    ],
    "ent_sinusitis_headache_fever": [
        "боль в лице и температура, давит в пазухах",
        "давит в пазухах, боль в лице и температура",
    ],
    "ent_vertigo_ent": [
        "головокружение и шум в ухе",
        "шум в ухе и головокружение",
    ],
}

# Если в packs id сценария отличается от ключа в SCENARIO_ALIASES — подставляем реальный id из scenario_packs
ALIAS_ID_TO_SCENARIO_ID: dict[str, str] = {
    "orthopedics_knee_trauma": "orthopedics_knee_after_fall",
    "orthopedics_low_back_radicular": "orthopedics_back_pain_leg_radiation",
    "orthopedics_shoulder_instability": "orthopedics_shoulder_after_overhead",
    "urinary_dysuria_frequency": "urinary_painful_urination",
    "urinary_upper_tract_concern": "urinary_flank_pain_fever",
    "urinary_blood_or_abnormal_urine": "urinary_blood_in_urine",
    "neuro_arm_weakness": "neuro_numb_arm_face",
    "neuro_dizziness": "neuro_dizziness_vertigo",
    "neuro_headache_red_flags": "neuro_headache_fever",
    "gastro_vomiting_dehydration": "gastro_nausea_vomiting",
    "cardio_exertional_chest_pain": "cardio_chest_pain_exertion",
    "cardio_chest_pressure": "cardio_chest_pain_rest",
    "fatigue_hair_nails": "fatigue_deficiency_fatigue_hair_loss",
    "fatigue_general": "fatigue_deficiency_fatigue_general",
    "allergy_rash_itching": "allergy_skin_itching_rash",
    "allergy_urticaria_swelling": "allergy_skin_hives",
    "allergy_skin_eczema_flare": "allergy_skin_eczema_flare",
    "allergy_skin_insect_bite_reaction": "allergy_skin_insect_bite_reaction",
    "cardio_fainting": "cardio_fainting",
}


def _tokenize(text: str) -> set[str]:
    return {x.strip() for x in text.lower().replace("ё", "е").replace(",", " ").replace(".", " ").split() if x.strip()}


def _overlap_score(a: str, b: str) -> float:
    ta = _tokenize(a)
    tb = _tokenize(b)
    if not ta or not tb:
        return 0.0
    inter = ta.intersection(tb)
    if not inter:
        return 0.0
    return len(inter) / max(len(tb), 1)


def _resolve_alias_scenario_id(normalized_text: str) -> tuple[str, float]:
    best_id = ""
    best_score = 0.0
    best_alias_len = 0
    for scenario_id, aliases in SCENARIO_ALIASES.items():
        for alias in aliases:
            score = _overlap_score(normalized_text, alias)
            if alias in normalized_text:
                score = max(score, 0.95)
            alias_len = len(alias.strip())
            if score > best_score or (score == best_score and alias_len > best_alias_len):
                best_score = score
                best_id = scenario_id
                best_alias_len = alias_len
    return best_id, best_score


def _pack_to_item(pack: ScenarioPack, score: float = 0.0) -> dict[str, Any]:
    chief = (pack.chief_complaint_patterns[0] if pack.chief_complaint_patterns else pack.title_ru) or ""
    return {
        "id": pack.id,
        "category": pack.category,
        "title_ru": pack.title_ru,
        "score": score,
        "chief_complaint": chief,
        "must_ask": pack.must_ask,
        "red_flags": pack.red_flags,
        "likely_hypotheses": pack.likely_hypotheses,
        "hypotheses": pack.likely_hypotheses,
        "possible_tests": pack.possible_tests,
        "self_care": pack.self_care,
        "care_path": pack.care_path,
        "source_path": pack.source_path,
    }


def _load_all_scenarios() -> list[dict[str, Any]]:
    """Список сценариев в виде dict (id, chief_complaint, must_ask, hypotheses, …) для alias/overlap логики."""
    try:
        packs = load_all_scenario_packs()
        return [_pack_to_item(p) for p in packs]
    except Exception:
        pass
    return []


def _norm(text: str) -> str:
    value = str(text or "").lower().strip()
    value = value.replace("ё", "е")
    value = re.sub(r"[^a-zа-я0-9\s]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _looks_febrile_respiratory(text: str) -> bool:
    t = _norm(text)
    has_fever = any(k in t for k in ("температур", "лихорад", "жар", "39", "38"))
    resp_hits = sum(
        1
        for k in ("каш", "мокрот", "сопл", "насморк", "горл", "орви", "простуд", "дых")
        if k in t
    )
    return has_fever and resp_hits >= 2


def _has_pediatric_context(text: str) -> bool:
    t = _norm(text)
    return any(k in t for k in ("ребен", "ребён", "ребенка", "ребёнка", "дет", "малыш", "педиатр"))


def _alias_matches_febrile_respiratory(alias_or_lookup_id: str) -> bool:
    sid = str(alias_or_lookup_id or "").strip().lower()
    if sid.startswith("respiratory_"):
        return True
    # allow soft match for common upper-respiratory aliases
    return any(k in sid for k in ("resp", "cough", "throat", "uri"))


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _category_hint_score(text: str, category: str) -> float:
    hints = _ALIAS_HINTS.get(category, [])
    score = 0.0
    for hint in hints:
        if hint in text:
            score += 0.35
    return score


def _context_priority_adjustment(text: str, category: str) -> float:
    """
    Quality-pass heuristic:
    - boosts category that strongly matches user context (phase-2 branches),
    - mildly penalizes mismatched categories to reduce cross-branch leakage.
    """
    t = _norm(text)
    is_pediatric = any(k in t for k in ("ребен", "ребён", "младен", "дет", "педиатр", "новорож"))
    is_women = any(
        k in t
        for k in (
            "месячн",
            "цикл",
            "менстру",
            "овуляц",
            "беремен",
            "послеродов",
            "лактац",
            "влагалищ",
            "гинек",
        )
    )
    is_ent = any(
        k in t
        for k in (
            "ухо",
            "нос",
            "синус",
            "миндалин",
            "осипл",
            "шум в ушах",
            "заложенность носа",
            "боль в пазух",
        )
    )

    cfg = get_scenario_ranking_calibration()
    w = cfg.get("context_weights") if isinstance(cfg.get("context_weights"), dict) else {}
    pediatric_match_boost = float(w.get("pediatric_match_boost", 0.75))
    women_health_match_boost = float(w.get("women_health_match_boost", 0.75))
    ent_match_boost = float(w.get("ent_match_boost", 0.55))
    women_health_when_pediatric_penalty = float(w.get("women_health_when_pediatric_penalty", -0.15))
    pediatric_when_women_health_penalty = float(w.get("pediatric_when_women_health_penalty", -0.15))
    resp_or_oral_when_ent_penalty = float(w.get("resp_or_oral_when_ent_penalty", -0.10))

    adj = 0.0
    if is_pediatric:
        if category == "pediatric":
            adj += pediatric_match_boost
        elif category == "women_health":
            adj += women_health_when_pediatric_penalty
    if is_women:
        if category == "women_health":
            adj += women_health_match_boost
        elif category == "pediatric":
            adj += pediatric_when_women_health_penalty
    if is_ent:
        if category == "ent":
            adj += ent_match_boost
        elif category in ("respiratory", "oral_cavity"):
            adj += resp_or_oral_when_ent_penalty
    return adj


def score_scenario_pack(user_text: str, pack: ScenarioPack) -> float:
    text = _norm(user_text)
    if not text:
        return 0.0

    score = _category_hint_score(text, pack.category)
    score += _context_priority_adjustment(text, pack.category)

    for pattern in pack.chief_complaint_patterns:
        p = _norm(pattern)
        if not p:
            continue
        if p in text or text in p:
            score += 1.8
        else:
            ratio = _similarity(text, p)
            if ratio >= 0.75:
                score += 1.2 * ratio
            elif ratio >= 0.55:
                score += 0.7 * ratio

    for hypothesis in pack.likely_hypotheses:
        hp = _norm(hypothesis.replace("_", " "))
        if hp and hp in text:
            score += 0.4

    if pack.category == "oral_cavity" and any(k in text for k in ("зуб", "десн", "рот", "язык", "щек", "челюст")):
        score += 0.9

    return round(max(score, 0.0), 4)


def resolve_best_scenario(user_message: str, max_results: int = 5, min_score: float = 0.55) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for pack in load_all_scenario_packs():
        score = score_scenario_pack(user_message, pack)
        if score < min_score:
            continue
        candidates.append(_pack_to_item(pack, score))
    candidates.sort(key=lambda x: (x["score"], x.get("category") == "oral_cavity"), reverse=True)
    return candidates[:max_results]


def resolve_primary_scenario(user_text: str) -> dict[str, Any] | None:
    """
    Нормализует текст → alias-матч по SCENARIO_ALIASES → при промахе overlap по контенту сценариев + branch bonus.
    """
    normalized_text = (user_text or "").strip()
    detected_branch = ""

    if input_normalizer and hasattr(input_normalizer, "normalize"):
        try:
            normalized = input_normalizer.normalize(user_text)
            if isinstance(normalized, dict):
                normalized_text = normalized.get("normalized_text", normalized_text) or normalized_text
                detected_branch = normalized.get("detected_branch", "") or ""
            elif isinstance(normalized, str):
                normalized_text = normalized or normalized_text
        except Exception:
            pass

    # Clinical quality guard: avoid neuro/other drift when text strongly matches febrile respiratory pattern.
    if _looks_febrile_respiratory(normalized_text):
        detected_branch = "respiratory"

    scenarios = _load_all_scenarios()
    if not scenarios:
        return None

    febrile_resp = _looks_febrile_respiratory(normalized_text)
    ped_ctx = _has_pediatric_context(normalized_text)

    # 1. Alias-based direct route
    alias_id, alias_score = _resolve_alias_scenario_id(normalized_text)
    if alias_id and alias_score >= 0.55:
        lookup_id = ALIAS_ID_TO_SCENARIO_ID.get(alias_id, alias_id)
        # Quality guard: for clear febrile-respiratory text do not lock into unrelated alias routes.
        if febrile_resp and not _alias_matches_febrile_respiratory(lookup_id):
            alias_id = ""
        # Quality guard: pediatric alias only when child context is present.
        if alias_id and str(lookup_id).lower().startswith("pediatric_") and not ped_ctx:
            alias_id = ""
        if alias_id:
            lookup_id = ALIAS_ID_TO_SCENARIO_ID.get(alias_id, alias_id)
        else:
            lookup_id = ""
        if lookup_id:
            for item in scenarios:
                if str(item.get("id", "")).lower() == lookup_id.lower():
                    item["score"] = alias_score
                    return item
            for item in scenarios:
                if str(item.get("id", "")).lower() == alias_id.lower():
                    item["score"] = alias_score
                    return item
        # нет сценария с таким id — идём в overlap (branch bonus подберёт близкий)

    # 2. Fallback: keyword overlap по полям сценария + branch bonus
    best_item = None
    best_score = 0.0

    for item in scenarios:
        score = 0.0
        scenario_id = str(item.get("id", "")).lower()
        chief = str(item.get("chief_complaint", "")).lower()
        text_pool = [scenario_id, chief]
        for q in item.get("must_ask", []) or []:
            text_pool.append(str(q).lower())
        for hyp in item.get("hypotheses", item.get("likely_hypotheses", [])) or []:
            text_pool.append(str(hyp).lower())

        local_score = 0.0
        for text_piece in text_pool:
            if not text_piece:
                continue
            local_score = max(local_score, _overlap_score(normalized_text, text_piece))
            if text_piece in normalized_text:
                local_score = max(local_score, 0.85)

        if detected_branch:
            if detected_branch in scenario_id:
                local_score += _branch_bonus("default")
            if detected_branch == "oral_cavity" and scenario_id.startswith("oral_"):
                local_score += _branch_bonus("default")
            if detected_branch == "allergy_skin" and scenario_id.startswith("allergy_"):
                local_score += _branch_bonus("default")
            if detected_branch == "orthopedics" and scenario_id.startswith("orthopedics_"):
                local_score += _branch_bonus("default")
                if detect_ortho_zone:
                    try:
                        zone = detect_ortho_zone(normalized_text)
                        if zone:
                            if zone in scenario_id:
                                local_score += 0.25
                            if zone == "low_back" and "back" in scenario_id:
                                local_score += 0.25
                    except Exception:
                        pass
            if detected_branch == "cardio" and "cardio" in scenario_id:
                local_score += _branch_bonus("default")
            if detected_branch == "gastro" and scenario_id.startswith("gastro_"):
                local_score += _branch_bonus("default")
            if detected_branch == "respiratory" and scenario_id.startswith("respiratory_"):
                local_score += _branch_bonus("default")
            if detected_branch == "neuro" and scenario_id.startswith("neuro_"):
                local_score += _branch_bonus("default")
            if detected_branch == "urinary" and scenario_id.startswith("urinary_"):
                local_score += _branch_bonus("default")
            if detected_branch == "fatigue_deficiency" and scenario_id.startswith("fatigue_"):
                local_score += _branch_bonus("default")
            if detected_branch == "women_health" and scenario_id.startswith("women_health_"):
                local_score += _branch_bonus("women_health")
            if detected_branch == "pediatric" and scenario_id.startswith("pediatric_"):
                local_score += _branch_bonus("pediatric")
            if detected_branch == "ent" and scenario_id.startswith("ent_"):
                local_score += _branch_bonus("ent")
        local_score += _context_priority_adjustment(normalized_text, str(item.get("category") or ""))
        if febrile_resp and scenario_id.startswith("urinary_"):
            local_score -= 0.45
        if febrile_resp and scenario_id.startswith("pediatric_") and not ped_ctx:
            local_score -= 0.45

        if local_score > best_score:
            best_score = local_score
            best_item = item

    if best_score >= 0.35 and best_item is not None:
        best_item["score"] = best_score
        return best_item

    return None
