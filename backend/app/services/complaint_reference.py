"""Complaint reference loader and resolver for complaint-driven orchestration."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from app.services.complaint_priority import rebuild_priority_index
from app.services.medical_core_bridge import get_medical_core_complaints

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_REFERENCE_FILE = _PROJECT_ROOT / "medical_knowledge" / "diseases" / "complaints_reference.json"
_SCENARIOS_FILE = _PROJECT_ROOT / "medical_knowledge" / "diseases" / "complaint_scenarios_short.json"
_COMPLAINT_SCRIPTS_DIR = _PROJECT_ROOT / "medical_knowledge" / "complaints"
_CACHE: list[dict[str, Any]] | None = None

DEFAULT_DIALOGUE_META = {
    "ask_one_by_one": True,
    "wait_for_answer": True,
    "analyze_and_follow_up": True,
    "pause_seconds_before_next": 3,
    "acknowledge_before_next": ["ок", "понял", "ясно", "ага"],
}
DEFAULT_LABS_META = {
    "recommend_if_uncertain": True,
    "ask_dialog_to_attach": True,
    "save_dialog_with_documents": True,
}


def _labs_from_complaint(item: dict[str, Any]) -> list[str]:
    """Извлечь suggested_labs из labs_if_needed или additional_tests_if_needed."""
    out: list[str] = []
    for key in ("labs_if_needed", "additional_tests_if_needed"):
        for x in (item.get(key) or []):
            if isinstance(x, dict):
                t = str(x.get("test") or "").strip()
                if t:
                    out.append(t)
            elif isinstance(x, str) and x.strip():
                out.append(x.strip())
    return out


def _load_items() -> list[dict[str, Any]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    if not _REFERENCE_FILE.exists():
        _CACHE = []
        return _CACHE
    try:
        payload = json.loads(_REFERENCE_FILE.read_text(encoding="utf-8"))
    except Exception:
        _CACHE = []
        return _CACHE
    items = payload.get("items") if isinstance(payload, dict) else []
    rows = [x for x in (items or []) if isinstance(x, dict)]
    rows.extend(_load_complaint_scripts())
    rows.extend(get_medical_core_complaints())
    _CACHE = _apply_scenario_overrides(rows)
    return _CACHE


def _load_complaint_scripts() -> list[dict[str, Any]]:
    if not _COMPLAINT_SCRIPTS_DIR.exists():
        return []
    out: list[dict[str, Any]] = []
    for fp in sorted(_COMPLAINT_SCRIPTS_DIR.glob("*.json")):
        try:
            item = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        out.append(
            {
                "id": str(item.get("id") or fp.stem),
                "complaint": name,
                "name": name,
                "category": str(item.get("category") or "Общая медицина"),
                "description": str(item.get("diagnosis_logic") or item.get("description") or "").strip(),
                "symptoms": list(item.get("key_symptoms") or []),
                "anamnesis_questions": list(item.get("must_ask") or item.get("must_ask_questions") or []),
                "red_flags": list(item.get("red_flags") or item.get("red_flags_specific") or []),
                "suggested_labs": _labs_from_complaint(item),
                "nutrition_recommendations": list(item.get("diet") or item.get("nutrition_advice") or []),
                "physical_exercise_prevention_rehabilitation": list(item.get("exercise") or item.get("physical_activity_advice") or []),
                "common_user_phrasings": list(item.get("user_phrases") or item.get("common_user_phrasings") or []),
                "key_symptoms": list(item.get("key_symptoms") or []),
                "must_ask_questions": list(item.get("must_ask") or item.get("must_ask_questions") or []),
                "optional_questions": list(item.get("optional_questions") or []),
                "red_flags_specific": list(item.get("red_flags") or item.get("red_flags_specific") or []),
                "likely_labs": _labs_from_complaint(item),
                "urgency_level": str(item.get("urgency_level") or ""),
                "likely_causes": list(item.get("likely_causes") or []),
                "top_hypotheses": list(item.get("top_hypotheses") or []),
                "first_line_non_drug_steps": list(item.get("treatment_basic") or item.get("first_line_non_drug_steps") or []),
                "source": "complaint_scripts_pack",
            }
        )
    return out


def _load_scenarios() -> list[dict[str, Any]]:
    if not _SCENARIOS_FILE.exists():
        return []
    try:
        payload = json.loads(_SCENARIOS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = payload.get("items") if isinstance(payload, dict) else []
    return [x for x in (items or []) if isinstance(x, dict)]


def _merge_unique(base: list[str], extra: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in (base or []) + (extra or []):
        s = str(x or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _apply_scenario_overrides(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scenarios = _load_scenarios()
    if not scenarios:
        return rows
    by_id = {str(x.get("id") or "").strip().lower(): x for x in scenarios}
    by_name = {str(x.get("name") or "").strip().lower(): x for x in scenarios if str(x.get("name") or "").strip()}
    out: list[dict[str, Any]] = []
    matched_ids: set[str] = set()
    for item in rows:
        cur = dict(item)
        item_id = str(cur.get("id") or "").strip().lower()
        item_name = str(cur.get("complaint") or cur.get("name") or "").strip().lower()
        scenario = by_id.get(item_id) or by_name.get(item_name)
        if not scenario:
            out.append(cur)
            continue
        matched_ids.add(str(scenario.get("id") or "").strip().lower())
        must_ask = [str(x).strip() for x in (scenario.get("must_ask_questions") or []) if str(x).strip()]
        opt_ask = [str(x).strip() for x in (scenario.get("optional_questions") or []) if str(x).strip()]
        cur["anamnesis_questions"] = _merge_unique(must_ask, list(cur.get("anamnesis_questions") or []) + opt_ask)
        cur["red_flags"] = _merge_unique(list(cur.get("red_flags") or []), list(scenario.get("red_flags_specific") or []))
        cur["suggested_labs"] = _merge_unique(list(cur.get("suggested_labs") or []), list(scenario.get("likely_labs") or []))
        cur["nutrition_recommendations"] = _merge_unique(
            list(cur.get("nutrition_recommendations") or []),
            list(scenario.get("nutrition_advice") or []),
        )
        cur["physical_exercise_prevention_rehabilitation"] = _merge_unique(
            list(cur.get("physical_exercise_prevention_rehabilitation") or []),
            list(scenario.get("physical_activity_advice") or []),
        )
        for fld in (
            "common_user_phrasings",
            "key_symptoms",
            "typical_triggers",
            "differentiators",
            "must_ask_questions",
            "optional_questions",
            "red_flags_specific",
            "likely_labs",
            "likely_imaging",
            "first_line_non_drug_steps",
            "medication_options_safe_general",
            "medication_options_doctor_only",
            "nutrition_advice",
            "physical_activity_advice",
            "prevention",
            "what_makes_this_less_likely",
            "when_to_refer",
            "urgency_level",
            "expected_short_answer",
        ):
            if fld in scenario:
                cur[fld] = scenario.get(fld)
        out.append(cur)
    # Add unmatched scenarios as synthetic complaint-first entries.
    for sc in scenarios:
        sid = str(sc.get("id") or "").strip().lower()
        if not sid or sid in matched_ids:
            continue
        out.append(
            {
                "id": sid,
                "complaint": str(sc.get("name") or sid),
                "name": str(sc.get("name") or sid),
                "category": str(sc.get("category") or "Общая медицина"),
                "description": str(sc.get("concise_description") or ""),
                "symptoms": list(sc.get("key_symptoms") or []),
                "anamnesis_questions": _merge_unique(
                    list(sc.get("must_ask_questions") or []),
                    list(sc.get("optional_questions") or []),
                ),
                "red_flags": list(sc.get("red_flags_specific") or []),
                "suggested_labs": list(sc.get("likely_labs") or []),
                "nutrition_recommendations": list(sc.get("nutrition_advice") or []),
                "physical_exercise_prevention_rehabilitation": list(sc.get("physical_activity_advice") or []),
                "common_user_phrasings": list(sc.get("common_user_phrasings") or []),
                "key_symptoms": list(sc.get("key_symptoms") or []),
                "must_ask_questions": list(sc.get("must_ask_questions") or []),
                "optional_questions": list(sc.get("optional_questions") or []),
                "red_flags_specific": list(sc.get("red_flags_specific") or []),
                "likely_labs": list(sc.get("likely_labs") or []),
                "urgency_level": str(sc.get("urgency_level") or ""),
                "expected_short_answer": str(sc.get("expected_short_answer") or ""),
                "source": "complaint_scenarios_short",
            }
        )
    return out


_STRUCTURAL_STOPWORDS = frozenset({
    "области", "тела", "симптомы", "длительность", "выраженность", "медикаменты",
    "тревожные", "признаки", "перечисленного", "более", "недели", "принимал",
    "очень", "некомфортно", "выраженные",
    # Разговорные «пустышки» и префиксы UI — иначе матчинг цепляется к карточкам с «что это», «вопросы»…
    "вопрос", "вопросы", "что", "это", "этот", "этой", "этом", "так", "вот",
    "меня", "мне", "тебя", "тебе", "нас", "вас", "уже", "ещё", "еще", "как",
    "если", "когда", "есть", "просто", "всем", "всё", "все", "него",
    "нам", "вам",
    # Указательные / конструкции, дающие ложные попадания («этого пятна», «вместо этого»…)
    "этого", "этим", "этих", "этой", "вместо", "должна", "должен", "должны", "должно",
    "целыми", "днями",
})


def _tokens(text: str) -> set[str]:
    s = re.sub(r"[^\w\sа-яёa-z0-9]", " ", (text or "").lower())
    return {w for w in s.split() if len(w) >= 3 and w not in _STRUCTURAL_STOPWORDS}


def _has_blood_index_or_oncophobia_query(norm_q: str) -> bool:
    """Жалобы на показатели ОАК / страх рака по анализу — отдельный кластер от мочевых и ОРВИ."""
    n = (norm_q or "").lower().replace("ё", "е")
    if any(
        x in n
        for x in (
            "лимфоцит",
            "лейкоцит",
            "тромбоцит",
            "гемоглобин",
            "лейкоформул",
            "нейтрофил",
            "моноцит",
            "эозинофил",
            "онкомарк",
            "биопс",
            "анализ кров",
            "общий анализ",
        )
    ):
        return True
    if "боюсь" in n and "рак" in n and any(x in n for x in ("анализ", "лимфо", "лейко", "гемоглоб", "оак", "кров")):
        return True
    return False


def _has_postpartum_emotional_query(norm_q: str) -> bool:
    """Плач/апатия в контексте младенца или послеродового периода — не щитовидка/диабет по умолчанию."""
    n = (norm_q or "").lower().replace("ё", "е")
    emotional = any(
        x in n for x in ("плачу", "плач ", "слез", "слезы", "слёз", "тоск", "апати", "депресс", "бессмысл")
    )
    baby_or_postpartum = any(
        x in n
        for x in (
            "ребенок",
            "ребенку",
            "ребенка",
            "ребёнок",
            "ребёнку",
            "ребёнка",
            "младенец",
            "новорожд",
            "груднич",
            "роды",
            "родила",
            "послерод",
            "после род",
            "построд",
            "материн",
            "радоваться",
        )
    )
    return emotional and baby_or_postpartum


def _has_parental_academic_pressure_query(norm_q: str) -> bool:
    """Давление родителей на учёбу/анализы + истощение — отдельный сценарий, не послеродовый и не соматика «по словам»."""
    n = (norm_q or "").lower().replace("ё", "е")
    parents = any(x in n for x in ("родител", "мама", "папа", "мать", "отец"))
    family_pressure = any(
        x in n
        for x in (
            "давят",
            "требуют",
            "требует",
            "контролиру",
            "заставля",
            "орут",
            "учись",
            "учиться",
            "сдавай",
            "сдавать",
            "анализы",
            "анализ ",
            "оценк",
            "двойк",
            "троек",
            "недотяг",
            "экзамен",
        )
    ) or ("давлен" in n and "родител" in n)
    school_or_tests = any(
        x in n
        for x in (
            "учеб",
            "учись",
            "учиться",
            "школ",
            "институт",
            "универ",
            "экзамен",
            "оценк",
            "дз",
            "урок",
            "анализы",
            "анализ ",
            "контрольн",
        )
    )
    distress = any(
        x in n
        for x in (
            "ничего не хочу",
            "не хочу",
            "не хочется",
            "вымота",
            "устал",
            "устала",
            "надоело",
            "опустош",
            "апати",
            "депресс",
            "тревож",
            "плачу",
            "слез",
            "бесит",
        )
    )
    return bool(parents and family_pressure and (school_or_tests or distress))


def _has_knee_postinjury_training_return_query(norm_q: str) -> bool:
    """Колено после травмы/операции + нельзя нормально тренироваться длительно — отдельный сценарий поддержки, не ОРВИ/ЖКТ."""
    n = (norm_q or "").lower().replace("ё", "е")
    knee = any(x in n for x in ("колен", "мениск", "коленн", "связок колен"))
    injury = any(x in n for x in ("травм", "операц", "разрыв", "вывих", "ушиб", "перелом", "артроскоп", "порвал"))
    training = any(x in n for x in ("трениров", "спорт", "нагрузк", "зал", "бег", "присед"))
    prolonged = any(
        x in n
        for x in (
            "месяц",
            "месяцев",
            "недел",
            "давно",
            "до сих пор",
            "досих пор",
            "третий",
            "четверт",
            "полгода",
            "год",
        )
    )
    return bool(knee and injury and training and prolonged)


def _has_health_anxiety_mortality_fear_query(norm_q: str) -> bool:
    """Страх смерти / «что-то серьёзное» на фоне тревоги без кластера ОАК/онко (его ведёт отдельный сценарий)."""
    n = (norm_q or "").lower().replace("ё", "е")
    if _has_blood_index_or_oncophobia_query(n):
        return False
    fear = any(x in n for x in ("боюсь", "страшно", "тревог", "паник", "переживаю", "накрывает", "волнуюсь"))
    death_or_doom = any(x in n for x in ("умру", "умер", "смерт", "жизн конч", "не вылеч", "неизлечим")) or (
        "серьезн" in n
        and any(x in n for x in ("вдруг", "боюсь", "тревог", "умру", "умер", "смерт", "болезн", "симптом"))
    )
    return bool(fear and death_or_doom)


def _has_prolonged_appetite_loss_query(norm_q: str) -> bool:
    """Длительно нет аппетита / почти не ест — не острый «один день плохо поел»."""
    n = (norm_q or "").lower().replace("ё", "е")
    appetite_loss = bool(
        any(
            x in n
            for x in (
                "нет аппетита",
                "аппетита нет",
                "аппетит пропал",
                "потеря аппетита",
                "пропал аппетит",
                "не ем",
                "ничего не ем",
                "почти ничего не ем",
                "почти не ем",
                "не могу есть",
                "есть не могу",
                "не хочу есть",
                "не хочется есть",
            )
        )
    )
    prolonged = any(
        x in n
        for x in (
            "месяц",
            "месяцев",
            "недел",
            "два месяца",
            "три месяца",
            "полтора месяца",
            "полтора",
            "долго",
            "давно",
        )
    )
    return bool(appetite_loss and prolonged)


def _has_premenstrual_mood_sweet_craving_query(norm_q: str) -> bool:
    """ПМС-подобный кластер: перед менструацией настроение/раздражительность и тяга к сладкому."""
    n = (norm_q or "").lower().replace("ё", "е")
    cycle_ctx = any(
        x in n
        for x in (
            "перед месячн",
            "перед менстру",
            "пмс",
            "пременстру",
            "предменстру",
            "до месячн",
            "до менстру",
            "предменструальн",
            "за несколько дней до месячн",
            "за несколько дней до менстру",
        )
    )
    mood_or_craving = any(
        x in n
        for x in (
            "настроен",
            "раздражит",
            "злюсь",
            "злость",
            "тревог",
            "плачу",
            "слез",
            "сладк",
            "сахар",
            "тяга к",
            "хочется слад",
            "срываюсь на еду",
        )
    )
    return bool(cycle_ctx and mood_or_craving)


def _has_chronic_fatigue_months_no_recovery_query(norm_q: str) -> bool:
    """Многонедельная/многомесячная усталость и отсутствие сил (в т.ч. после сна) — не «устал вчера»."""
    n = (norm_q or "").lower().replace("ё", "е")
    strong_fatigue = any(
        x in n
        for x in (
            "устал",
            "усталост",
            "нет сил",
            "сил нет",
            "разбит",
            "вымотан",
            "энергии нет",
            "нет энергии",
            "вялост",
        )
    )
    sleep_no_recovery = any(x in n for x in ("после сна", "сон не", "не высыпа", "не высыпаюсь")) and any(
        x in n for x in ("сил нет", "нет сил", "устал", "усталост", "разбит", "энергии нет", "нет энергии")
    )
    fatigue = bool(strong_fatigue or sleep_no_recovery)
    prolonged = any(
        x in n
        for x in (
            "полгода",
            "пол года",
            "полтора года",
            "уже год",
            "целый год",
            "больше года",
            "месяц",
            "месяцев",
            "несколько месяц",
            "три месяца",
            "четыре месяца",
            "пять месяц",
            "шесть месяц",
            "несколько недел",
            "недел",
            "давно",
        )
    )
    return bool(fatigue and prolonged)


def _has_gas_bloating_digestion_query(norm_q: str) -> bool:
    """Вздутие / газы / метеоризм на фоне жалоб на живот или пищеварение — базовый ЖКТ-кластер."""
    n = (norm_q or "").lower().replace("ё", "е")
    bloating_or_gas = any(
        x in n
        for x in (
            "вздут",
            "пучит",
            "метеоризм",
            "газы",
            "газов",
            "газообраз",
            "пука",
            "урчан",
        )
    )
    if not bloating_or_gas:
        return False
    digestion_ctx = any(
        x in n
        for x in (
            "живот",
            "брюш",
            "пищевар",
            "переварива",
            "жкт",
            "кишечник",
            "кишечн",
            "желуд",
            "желудк",
            "после еды",
            "после приема пищ",
            "после приёма пищ",
        )
    )
    return bool(digestion_ctx)


def _has_heavy_menstrual_fatigue_hair_loss_query(norm_q: str) -> bool:
    """Обильные менструации на фоне усталости и выпадения волос — частый кластер дефицита железа/гормонального дисбаланса (не «просто ПМС»)."""
    n = (norm_q or "").lower().replace("ё", "е")
    menstrual = any(x in n for x in ("месячн", "менструац", "менструа", "менстру", "месячные"))
    heavy = any(
        x in n
        for x in (
            "обильн",
            "менорраг",
            "много кров",
            "сильн кровотеч",
            "сильные месячные",
            "тяжелые месячные",
            "обильные менстру",
        )
    )
    fatigue = any(x in n for x in ("усталост", "усталый", "устала", "нет сил", "слабост", "разбит", "астен", "истощ"))
    hair = bool(
        ("выпадение волос" in n)
        or ("выпадают волос" in n)
        or ("выпадают" in n and "волос" in n)
        or ("выпаден" in n and "волос" in n)
        or ("алопец" in n)
        or ("волос лез" in n)
        or ("волосы лез" in n)
    )
    return bool(menstrual and heavy and fatigue and hair)


def _has_heavy_menses_iron_priority_context(norm_q: str) -> bool:
    """Обильные месячные + усталость или выпадение волос — приоритетнее «голой» астении при bypass справочника жалоб."""
    if _has_heavy_menstrual_fatigue_hair_loss_query(norm_q):
        return True
    n = (norm_q or "").lower().replace("ё", "е")
    menstrual = any(x in n for x in ("месячн", "менструац", "менструа", "менстру", "месячные"))
    heavy = any(
        x in n
        for x in (
            "обильн",
            "менорраг",
            "много кров",
            "сильн кровотеч",
            "сильные месячные",
            "тяжелые месячные",
            "обильные менстру",
        )
    )
    if not (menstrual and heavy):
        return False
    fatigue_like = any(
        x in n
        for x in ("усталост", "усталый", "устала", "нет сил", "слабост", "разбит", "астен", "истощ")
    )
    hair_like = bool(
        ("выпадение волос" in n)
        or ("выпадают волос" in n)
        or (("выпадают" in n or "выпаден" in n) and "волос" in n)
        or ("алопец" in n)
        or ("волос лез" in n)
        or ("волосы лез" in n)
        or ("волосы выпада" in n)
    )
    return bool(fatigue_like or hair_like)


def _has_irregular_cycle_women_query(norm_q: str) -> bool:
    n = (norm_q or "").lower().replace("ё", "е")
    if not any(x in n for x in ("цикл", "месячн", "менстру", "овуляц")):
        return False
    return any(
        x in n
        for x in (
            "нерегулярн",
            "не регулярн",
            "сбива",
            "сбился",
            "непредсказу",
            "скачет",
            "задержк",
            "раньше чем",
            "чаще чем",
            "два раза в месяц",
        )
    )


def _has_acne_skin_hormonal_women_query(norm_q: str) -> bool:
    n = (norm_q or "").lower().replace("ё", "е")
    return any(x in n for x in ("акне", "прыщ", "прыщи", "высыпан", "угри", "сыпь на лиц", "сыпь на кож"))


def _has_weight_plateau_women_query(norm_q: str) -> bool:
    n = (norm_q or "").lower().replace("ё", "е")
    return any(
        x in n
        for x in (
            "вес не уходит",
            "не худею",
            "не сбрасыва",
            "не снижается вес",
            "вес стоит",
            "не могу похудеть",
            "лишний вес не уходит",
            "на диете вес",
            "похудеть не получается",
        )
    )


def _has_hair_loss_diffuse_women_query(norm_q: str) -> bool:
    if _has_heavy_menstrual_fatigue_hair_loss_query(norm_q):
        return False
    n = (norm_q or "").lower().replace("ё", "е")
    hair = bool(
        ("выпадение волос" in n)
        or ("выпадают волос" in n)
        or ("выпадают" in n and "волос" in n)
        or ("выпаден" in n and "волос" in n)
        or ("алопец" in n)
        or ("волос лез" in n)
        or ("волосы лез" in n)
        or ("волосы выпада" in n)
    )
    return hair


def _has_persistent_fatigue_women_query(norm_q: str) -> bool:
    n = (norm_q or "").lower().replace("ё", "е")
    if _has_chronic_fatigue_months_no_recovery_query(n):
        return False
    if _has_adolescent_anhedonia_apathy_query(n):
        return False
    if _has_heavy_menstrual_fatigue_hair_loss_query(n):
        return False
    fatigue = any(x in n for x in ("усталост", "нет сил", "слабост", "разбит", "астен"))
    persistent = (
        ("после сна" in n and any(x in n for x in ("не восстанавливаюсь", "не отсыпаюсь", "не проходит", "не отдыхаюсь")))
        or ("постоянн" in n and "устал" in n)
        or ("постоянная усталость" in n)
        or ("все время устал" in n)
        or ("сильная усталость" in n)
    )
    return bool(fatigue and persistent)


def _has_low_mood_apathy_women_query(norm_q: str) -> bool:
    n = (norm_q or "").lower().replace("ё", "е")
    if _has_adolescent_anhedonia_apathy_query(n):
        return False
    if _has_health_anxiety_mortality_fear_query(n):
        return False
    mood = any(x in n for x in ("апати", "плохое настроение", "подавлен", "депресс", "тоск", "нет настроения", "ничего не радует"))
    women = any(
        x in n
        for x in (
            "месячн",
            "менстру",
            "цикл",
            "гормон",
            "менопауз",
            "беремен",
            "роды",
            "гинек",
            "женск",
            "послерод",
        )
    )
    return bool(mood and women)


def _has_edema_swelling_women_query(norm_q: str) -> bool:
    n = (norm_q or "").lower().replace("ё", "е")
    return any(x in n for x in ("отек", "отёк", "отечност", "отекают", "отеки"))


def _has_painful_periods_dysmenorrhea_women_query(norm_q: str) -> bool:
    n = (norm_q or "").lower().replace("ё", "е")
    menstrual = any(x in n for x in ("месячн", "менстру", "менструац"))
    pain = any(
        x in n
        for x in (
            "болезненн",
            "боль при менстру",
            "болит при менстру",
            "дисменоре",
            "колик",
            "спазм",
            "сильная боль",
            "невыносим боль",
        )
    )
    return bool(menstrual and pain)


def _has_sweet_craving_standalone_women_query(norm_q: str) -> bool:
    n = (norm_q or "").lower().replace("ё", "е")
    if _has_premenstrual_mood_sweet_craving_query(n):
        return False
    return any(
        x in n
        for x in (
            "тяга к сладк",
            "тянет на сладк",
            "хочется сладкого",
            "сильная тяга к сладкому",
            "люблю сладкое не могу",
            "не могу без сладкого",
        )
    )


def _has_nutrition_supplements_where_to_start_query(norm_q: str) -> bool:
    """Хочется выстроить питание и подобрать добавки, но неясно, с чего начать — отдельно от чистого «похудеть» и от лабораторной онкофобии."""
    n = (norm_q or "").lower().replace("ё", "е")
    has_supp = any(x in n for x in ("добавк", "биодобавк", "витамин", "бады"))
    if not has_supp:
        return False
    has_nutrition = any(
        x in n
        for x in (
            "правильно пита",
            "здоровое пита",
            "сбалансирован",
            "рацион",
            "питаться",
            "режим пита",
        )
    )
    if not has_nutrition and "питание" in n:
        has_nutrition = True
    if not has_nutrition:
        return False
    confused = any(
        x in n
        for x in (
            "не понимаю с чего начать",
            "не знаю с чего начать",
            "не понимаю, с чего начать",
            "не знаю, с чего начать",
            "не понимаю как начать",
            "не знаю как начать",
            "не понимаю с чего",
            "не знаю с чего",
        )
    )
    wants_pick = "подобрать" in n and "добавк" in n
    generic_start = "с чего начать" in n
    return bool(confused or wants_pick or generic_start)


def _has_adolescent_anhedonia_apathy_query(norm_q: str) -> bool:
    """Подросток (≈10–17 лет): ангедония/апатия/бессмысленность и нет сил — не кластер хронической усталости по месяцам."""
    n = (norm_q or "").lower().replace("ё", "е")
    if _has_chronic_fatigue_months_no_recovery_query(n):
        return False
    teen_age = bool(
        re.search(r"\b(10|11|12|13|14|15|16|17)\s*лет", n)
        or re.search(r"мне\s+(10|11|12|13|14|15|16|17)\b", n)
    )
    teen_ctx = any(x in n for x in ("подросток", "школьник", "школьниц", "9 класс", "10 класс", "11 класс"))
    if not (teen_age or teen_ctx):
        return False
    distress = any(
        x in n
        for x in (
            "не радует",
            "ничего не радует",
            "бессмыслен",
            "смысла нет",
            "апати",
            "тоск",
            "депресс",
            "пусто",
            "нет сил",
            "сил нет",
            "ничего не хочу",
            "не хочу",
        )
    )
    return bool(distress)


def search_complaint_reference(query: str, top_k: int = 1) -> list[dict[str, Any]]:
    norm_query = " ".join(str(query or "").lower().strip().split())
    words = _tokens(query)
    if not words:
        return []
    blood_lab_fear = _has_blood_index_or_oncophobia_query(norm_query)
    pp_emotional = _has_postpartum_emotional_query(norm_query)
    parent_pressure = _has_parental_academic_pressure_query(norm_query)
    knee_rehab_training = _has_knee_postinjury_training_return_query(norm_query)
    health_anxiety_mortality = _has_health_anxiety_mortality_fear_query(norm_query)
    prolonged_appetite_loss = _has_prolonged_appetite_loss_query(norm_query)
    premenstrual_mood_sweet = _has_premenstrual_mood_sweet_craving_query(norm_query)
    chronic_fatigue_months = _has_chronic_fatigue_months_no_recovery_query(norm_query)
    adolescent_anhedonia = _has_adolescent_anhedonia_apathy_query(norm_query)
    nutrition_supplements_start = _has_nutrition_supplements_where_to_start_query(norm_query)
    gas_bloating_digestion = _has_gas_bloating_digestion_query(norm_query)
    heavy_menstrual_fatigue_hair = _has_heavy_menstrual_fatigue_hair_loss_query(norm_query)
    irregular_cycle_women = _has_irregular_cycle_women_query(norm_query)
    acne_skin_hormonal_women = _has_acne_skin_hormonal_women_query(norm_query)
    weight_plateau_women = _has_weight_plateau_women_query(norm_query)
    hair_loss_diffuse_women = _has_hair_loss_diffuse_women_query(norm_query)
    persistent_fatigue_women = _has_persistent_fatigue_women_query(norm_query)
    low_mood_apathy_women = _has_low_mood_apathy_women_query(norm_query)
    edema_swelling_women = _has_edema_swelling_women_query(norm_query)
    painful_periods_women = _has_painful_periods_dysmenorrhea_women_query(norm_query)
    sweet_craving_standalone_women = _has_sweet_craving_standalone_women_query(norm_query)
    rows = _load_items()
    scored: list[tuple[float, dict[str, Any]]] = []
    for it in rows:
        hay_parts = [
            str(it.get("complaint") or ""),
            str(it.get("name") or ""),
            str(it.get("category") or ""),
            str(it.get("description") or ""),
            " ".join(str(x or "") for x in (it.get("symptoms") or [])),
            " ".join(str(x or "") for x in (it.get("anamnesis_questions") or [])),
            " ".join(str(x or "") for x in (it.get("common_user_phrasings") or [])),
            " ".join(str(x or "") for x in (it.get("key_symptoms") or [])),
            " ".join(str(x or "") for x in (it.get("must_ask_questions") or [])),
        ]
        hay = " ".join(hay_parts).lower()
        hits = sum(1 for w in words if w in hay)
        title_hits = sum(1 for w in words if w in str(it.get("complaint") or "").lower())
        exact_title = 1 if norm_query == " ".join(str(it.get("complaint") or "").lower().strip().split()) else 0
        symptom_hits = sum(
            1
            for w in words
            if any(w in str(x or "").lower() for x in (it.get("symptoms") or []))
        )
        phrasing_hits = sum(
            1
            for w in words
            if any(w in str(x or "").lower() for x in (it.get("common_user_phrasings") or []))
        )
        phrase_exact = 1 if any(norm_query and norm_query in str(x or "").lower() for x in (it.get("common_user_phrasings") or [])) else 0
        if hits <= 0:
            continue
        source_tag = str(it.get("source") or "").strip().lower()
        is_scenario = source_tag in ("complaint_scenarios_short", "complaint_scripts_pack")
        scenario_match_quality = max(title_hits, phrasing_hits) + phrase_exact
        scenario_boost = (6.0 + (4.0 if phrasing_hits > 0 else 0.0)) if (is_scenario and scenario_match_quality >= 1) else 0.0
        complaint_low = str(it.get("complaint") or "").lower()
        word_count = len([w for w in re.split(r"\s+", complaint_low.strip()) if w])
        noisy_penalty = -3.0 if any(x in complaint_low for x in ("привет ", "мой брат", "что это такое")) else 0.0
        if word_count >= 8 or any(x in complaint_low for x in ("у меня ", "что мне де", "что это")):
            noisy_penalty -= 5.0
        score = float(
            hits
            + title_hits * 2.2
            + symptom_hits * 1.5
            + phrasing_hits * 2.0
            + exact_title * 100.0
            + phrase_exact * 6.0
            + scenario_boost
            + noisy_penalty
        )
        cid = str(it.get("id") or "").lower()
        hay_l = hay.lower()
        if blood_lab_fear:
            if any(
                x in hay_l
                for x in (
                    "лимфоцит",
                    "лейкоцит",
                    "лейкоформул",
                    "оак",
                    "анализ кров",
                    "гемоглобин",
                    "тромбоцит",
                    "онкомарк",
                    "страх",
                    "тревог",
                )
            ):
                score += 28.0
            if any(x in hay_l for x in ("мочеиспуск", "цистит", "пузыр", "почечн", "уролог", "позыв")) and not any(
                x in norm_query for x in ("моч", "цистит", "позыв", "жжение", "писать", "туалет", "уролог")
            ):
                score -= 42.0
            title_low = complaint_low
            if cid.startswith("complaint_auto") and "лимфоцит" not in hay_l and "лейкоформул" not in hay_l:
                score -= 22.0
            if len(title_low) > 95 and "лимфоцит" not in title_low and "анализ кров" not in title_low:
                score -= 12.0
        if pp_emotional:
            if any(
                x in hay_l
                for x in (
                    "послерод",
                    "материн",
                    "депресс",
                    "тревог",
                    "психолог",
                    "эмоцион",
                    "плач",
                    "слез",
                    "младенец",
                )
            ):
                score += 34.0
            if any(x in hay_l for x in ("щитовид", "ттг", "гипотире", "гипертире", "диабет", "жажд", "инсулин", "мочеиспуск", "цистит")) and not any(
                x in norm_query for x in ("ттг", "щитовид", "диабет", "жажд", "сахар", "инсулин", "моч", "цистит", "позыв")
            ):
                score -= 40.0
            if cid.startswith("complaint_auto") and not any(x in hay_l for x in ("послерод", "материн", "психолог", "эмоцион", "младенец", "депресс")):
                score -= 26.0
            if any(x in hay_l for x in ("пятно на коже", "сыпь на коже", "зуд и выделения")) and not any(
                x in norm_query for x in ("пятн", "кож", "сыпь", "зуд", "выделен")
            ):
                score -= 30.0
        if parent_pressure:
            if cid == "complaint_parental_academic_pressure" or any(
                x in hay_l
                for x in (
                    "родител",
                    "учеб",
                    "школ",
                    "анализ",
                    "стресс",
                    "подрост",
                    "давлен",
                    "требова",
                    "контрол",
                    "апати",
                )
            ):
                score += 36.0
            if any(x in hay_l for x in ("послерод", "младенец", "груднич", "новорожд", "роды")) and not any(
                x in norm_query for x in ("роды", "родила", "послерод", "новорожд", "младенец", "ребен", "ребён")
            ):
                score -= 38.0
            if any(x in hay_l for x in ("лимфоцит", "лейкоформул", "оак", "онколог", "рак")) and not any(
                x in norm_query for x in ("лимфоцит", "лейкоцит", "оак", "анализ кров", "гемоглобин", "рак", "онколог")
            ):
                score -= 36.0
            if cid.startswith("complaint_auto") and "родител" not in hay_l and "учеб" not in hay_l and "школ" not in hay_l:
                score -= 24.0
        if knee_rehab_training:
            if cid == "complaint_knee_postinjury_training_return" or any(
                x in hay_l for x in ("колен", "мениск", "связок", "травм", "реабилит", "трениров", "операц")
            ):
                score += 34.0
            if any(x in hay_l for x in ("цистит", "мочеиспуск", "послерод", "лимфоцит", "онколог", "орви", "кашл", "насморк")) and not any(
                x in norm_query for x in ("моч", "цистит", "роды", "лимфоцит", "рак", "кашл", "насморк", "горл")
            ):
                score -= 38.0
            if cid.startswith("complaint_auto") and "колен" not in hay_l and "мениск" not in hay_l and "травм" not in hay_l:
                score -= 22.0
        if health_anxiety_mortality:
            if cid == "complaint_health_anxiety_mortality_fear" or any(
                x in hay_l for x in ("тревог", "паник", "ипохонд", "страх", "психолог", "катастроф", "смерт", "умру", "серьезн")
            ):
                score += 34.0
            if any(x in hay_l for x in ("лимфоцит", "лейкоформул", "оак", "анализ кров", "цистит", "орви", "кашл", "колен")) and not any(
                x in norm_query for x in ("лимфоцит", "лейкоцит", "оак", "анализ кров", "моч", "цистит", "кашл", "колен")
            ):
                score -= 38.0
            if cid.startswith("complaint_auto") and not any(x in hay_l for x in ("тревог", "паник", "смерт", "страх", "ипохонд", "психолог")):
                score -= 22.0
        if prolonged_appetite_loss:
            if cid == "complaint_prolonged_loss_of_appetite" or any(
                x in hay_l for x in ("аппетит", "питан", "жкт", "желуд", "тошн", "похуден", "истощен", "не ем")
            ):
                score += 34.0
            if any(x in hay_l for x in ("лимфоцит", "орви", "кашл", "колен", "цистит", "паник", "смерт")) and not any(
                x in norm_query for x in ("лимфоцит", "кашл", "колен", "моч", "цистит", "паник", "умру", "смерт")
            ):
                score -= 34.0
            if cid.startswith("complaint_auto") and "аппетит" not in hay_l and "питан" not in hay_l and "желуд" not in hay_l:
                score -= 22.0
        if premenstrual_mood_sweet:
            if cid == "complaint_premenstrual_mood_sweet_craving" or any(
                x in hay_l for x in ("месячн", "менстру", "пмс", "пременстру", "цикл", "гинек", "овуляц", "дисменор", "гормон")
            ):
                score += 34.0
            if any(x in hay_l for x in ("лимфоцит", "орви", "кашл", "колен", "цистит", "послерод", "онколог")) and not any(
                x in norm_query for x in ("лимфоцит", "кашл", "колен", "моч", "цистит", "роды", "рак")
            ):
                score -= 36.0
            if cid.startswith("complaint_auto") and "месячн" not in hay_l and "менстру" not in hay_l and "пмс" not in hay_l and "цикл" not in hay_l:
                score -= 22.0
        if chronic_fatigue_months:
            if cid == "complaint_chronic_fatigue_months_no_recovery" or any(
                x in hay_l for x in ("усталост", "слабост", "энерг", "сон", "ферритин", "ттг", "желез", "витамин", "анем", "гипотире")
            ):
                score += 34.0
            if any(x in hay_l for x in ("цистит", "орви", "кашл", "колен", "лимфоцит", "послерод", "паник")) and not any(
                x in norm_query for x in ("моч", "цистит", "кашл", "колен", "лимфоцит", "роды", "паник")
            ):
                score -= 34.0
            if cid.startswith("complaint_auto") and "усталост" not in hay_l and "слабост" not in hay_l and "энерг" not in hay_l and "сон" not in hay_l:
                score -= 22.0
        if adolescent_anhedonia:
            if cid == "complaint_adolescent_anhedonia_apathy" or any(
                x in hay_l for x in ("подросток", "школьн", "психолог", "депресс", "апати", "настроен", "бессмыслен", "суицид")
            ):
                score += 34.0
            if any(x in hay_l for x in ("лимфоцит", "орви", "колен", "цистит", "менопауз", "беремен")) and not any(
                x in norm_query for x in ("лимфоцит", "кашл", "колен", "моч", "цистит", "беремен")
            ):
                score -= 34.0
            if cid.startswith("complaint_auto") and "подрост" not in hay_l and "школьн" not in hay_l and "психолог" not in hay_l and "депресс" not in hay_l:
                score -= 22.0
        if nutrition_supplements_start:
            if cid == "complaint_nutrition_supplements_where_to_start" or any(
                x in hay_l for x in ("питани", "рацион", "добавк", "витамин", "биодобавк", "бады", "диетолог", "дефицит", "ферритин")
            ):
                score += 34.0
            if any(x in hay_l for x in ("лимфоцит", "цистит", "орви", "колен", "менопауз")) and not any(
                x in norm_query for x in ("лимфоцит", "кашл", "колен", "моч", "цистит", "беремен")
            ):
                score -= 34.0
            if cid.startswith("complaint_auto") and "питани" not in hay_l and "рацион" not in hay_l and "добавк" not in hay_l and "витамин" not in hay_l:
                score -= 22.0
        if gas_bloating_digestion:
            if cid == "complaint_gas_bloating" or any(
                x in hay_l for x in ("вздут", "газообраз", "метеоризм", "живот", "кишечник", "фермент", "fodmap", "пищевар")
            ):
                score += 34.0
            if any(x in hay_l for x in ("лимфоцит", "онколог", "инсульт", "инфаркт")) and not any(
                x in norm_query for x in ("лимфоцит", "рак", "инсульт", "инфаркт")
            ):
                score -= 34.0
            if cid.startswith("complaint_auto") and "вздут" not in hay_l and "газ" not in hay_l and "живот" not in hay_l and "кишечник" not in hay_l:
                score -= 22.0
        if heavy_menstrual_fatigue_hair:
            if cid == "complaint_heavy_menstrual_bleeding_fatigue_hair_loss" or any(
                x in hay_l
                for x in (
                    "менстру",
                    "месячн",
                    "обильн",
                    "менорраг",
                    "ферритин",
                    "желез",
                    "анем",
                    "гинек",
                    "волос",
                    "выпаден",
                    "ттг",
                    "щитовид",
                )
            ):
                score += 34.0
            if any(x in hay_l for x in ("лимфоцит", "цистит", "орви", "гастроэнтерит")) and not any(
                x in norm_query for x in ("лимфоцит", "цистит", "кашл", "понос", "рвот")
            ):
                score -= 34.0
            if cid.startswith("complaint_auto") and "менстру" not in hay_l and "месячн" not in hay_l and "ферритин" not in hay_l and "волос" not in hay_l:
                score -= 22.0
        _womens_pack_rules = (
            (irregular_cycle_women, "complaint_irregular_menstrual_cycle_women", ("цикл", "месячн", "менстру", "нерегуляр", "ттг", "гормон")),
            (acne_skin_hormonal_women, "complaint_acne_skin_hormonal_women", ("акне", "прыщ", "высыпан", "кож", "гормон")),
            (weight_plateau_women, "complaint_weight_plateau_women", ("вес", "худе", "похуд", "инсулин", "ттг", "глюкоз")),
            (hair_loss_diffuse_women, "complaint_hair_loss_diffuse_women", ("волос", "выпаден", "ферритин", "ттг")),
            (persistent_fatigue_women, "complaint_persistent_fatigue_women", ("усталост", "ферритин", "сон", "ттг", "слабост")),
            (low_mood_apathy_women, "complaint_low_mood_apathy_women", ("настроен", "апати", "депресс", "гормон", "психолог")),
            (edema_swelling_women, "complaint_edema_swelling_women", ("отек", "отёк", "отечност", "жидкост")),
            (painful_periods_women, "complaint_painful_periods_dysmenorrhea_women", ("болезнен", "менстру", "дисменоре", "боль", "месячн")),
            (sweet_craving_standalone_women, "complaint_sweet_craving_standalone_women", ("сладк", "тяга", "глюкоз", "инсулин")),
        )
        for _wf, _wcid, _wk in _womens_pack_rules:
            if not _wf:
                continue
            if cid == _wcid or any(_x in hay_l for _x in _wk):
                score += 34.0
            if cid.startswith("complaint_auto") and not any(_x in hay_l for _x in _wk):
                score -= 22.0
        scored.append((score, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in scored[: max(1, top_k)]]


def get_complaint_by_name(name: str) -> dict[str, Any] | None:
    target = " ".join(str(name or "").strip().lower().split())
    if not target:
        return None
    for item in _load_items():
        current = " ".join(str(item.get("complaint") or "").strip().lower().split())
        if current == target:
            return item
    return None


def get_complaint_reference_item_by_id(item_id: str) -> dict[str, Any] | None:
    """Полная карточка жалобы по id (после merge сценариев из complaint_scenarios_short)."""
    sid = str(item_id or "").strip().lower()
    if not sid:
        return None
    for row in _load_items():
        if isinstance(row, dict) and str(row.get("id") or "").strip().lower() == sid:
            return dict(row)
    return None


def complaint_meta(item: dict[str, Any] | None) -> dict[str, Any]:
    it = item if isinstance(item, dict) else {}
    return {
        "dialogue_meta": dict(DEFAULT_DIALOGUE_META),
        "labs_meta": dict(DEFAULT_LABS_META),
        "category": str(it.get("category") or "").strip(),
        "complaint": str(it.get("complaint") or "").strip(),
        "seasonality": dict(it.get("seasonality") or {}),
        "market_signal_cluster": str(it.get("market_signal_cluster") or "").strip(),
        "public_source_basis": list(it.get("public_source_basis") or []),
    }


def current_season_label() -> str:
    month = time.localtime().tm_mon
    if month in (12, 1, 2):
        return "зима"
    if month in (3, 4, 5):
        return "весна"
    if month in (6, 7, 8):
        return "лето"
    return "осень"


def get_prioritized_complaints(
    limit: int = 20,
    season: str | None = None,
    season_weight_multiplier: float = 1.0,
    demand_weight_multiplier: float = 1.0,
) -> list[dict[str, Any]]:
    """Prioritize complaints by seasonality + user complaint demand signals."""
    rows = _load_items()
    if not rows:
        return []
    season_label = (season or current_season_label()).strip().lower()
    priority = rebuild_priority_index(profiles=[], force=False)
    hot_words = {str(x.get("word") or "").lower(): int(x.get("count") or 0) for x in (priority.get("top_keywords") or [])[:120]}

    scored: list[tuple[float, dict[str, Any]]] = []
    for item in rows:
        complaint = str(item.get("complaint") or "")
        symptoms = [str(x or "") for x in (item.get("symptoms") or [])]
        seasonality = item.get("seasonality") or {}
        peaks = [str(x).strip().lower() for x in (seasonality.get("peak_seasons") or []) if str(x).strip()]
        blob = " ".join([complaint] + symptoms).lower()
        demand_boost = 0.0
        for word, cnt in hot_words.items():
            if word and word in blob:
                demand_boost += min(cnt * 0.05, 1.5)
        season_boost = (1.5 if season_label and season_label in peaks else (0.4 if seasonality.get("year_round") else 0.0)) * float(season_weight_multiplier or 1.0)
        demand_boost *= float(demand_weight_multiplier or 1.0)
        red_flag_boost = 0.2 if (item.get("red_flags") or []) else 0.0
        diagnostics_boost = 0.2 if (item.get("suggested_labs") or []) else 0.0
        score = season_boost + demand_boost + red_flag_boost + diagnostics_boost
        scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    top_items = [it for _, it in scored[: max(1, int(limit))]]
    normalized: list[dict[str, Any]] = []
    for it in top_items:
        row = dict(it or {})
        row["seasonality"] = dict(row.get("seasonality") or {})
        normalized.append(row)
    return normalized
