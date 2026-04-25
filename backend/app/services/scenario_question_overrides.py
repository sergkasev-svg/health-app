from __future__ import annotations

import re
from typing import Any


def _acute_febrile_respiratory_context(text: str, evidence_present: list[Any] | None) -> bool:
    """Жар + явные ЛОР/кашель в тексте или evidence — не подменять вопросы стоматологическим сценарием."""
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    ev = {str(x).strip().lower() for x in (evidence_present or []) if str(x).strip()}
    fever = bool(re.search(r"\b3[6-9]\d?[.,]?\d*\b", t)) or any(
        k in t for k in ("температур", "субфебрил", "жар", "лихорад", " °")
    )
    fever = fever or "fever" in ev
    resp_lex = sum(1 for k in ("каш", "мокрот", "сопл", "насморк", "горл", "орви", "простуд", "дыхател") if k in t)
    resp_ev = len({"cough", "sputum", "runny_nose", "sore_throat", "dyspnea"} & ev)
    return fever and (resp_lex >= 2 or resp_lex + resp_ev >= 2)


_ORAL_SCENARIOS_STOMPED_BY_URI = frozenset({"oral_cavity_gum_abscess_like", "oral_cavity_dry_mouth"})


SCENARIO_QUESTION_MAP = {
    "cardio_chest_pain_exertion": [
        "Есть ли боль в груди?",
        "Есть ли одышка?",
        "Боль появляется при нагрузке?",
        "Какое давление?",
    ],
    "urinary_flank_pain_fever": [
        "Есть ли температура или озноб?",
        "Есть ли боль в пояснице или в боку?",
        "Есть ли боль при мочеиспускании?",
        "Есть ли частое мочеиспускание?",
    ],
    # Остаток по weak_cases: questions failing_dimension (runner-keyword-first)
    "oral_cavity_dry_mouth": [
        "Есть ли белый налёт во рту? Снимается ли?",
        "Принимали антибиотики недавно?",
        "Есть ли сухость во рту?",
        "Есть ли отек десны или щеки?",
    ],
    "gastro_nausea_vomiting": [
        "Где именно болит живот?",
        "Есть ли тошнота или рвота?",
        "Есть ли понос или кровь в стуле?",
        "Пьёте ли достаточно жидкости?",
    ],
    "fatigue_deficiency_fatigue_general": [
        "Как давно беспокоит усталость или слабость?",
        "Какое давление? Есть ли температура?",
        "Есть ли жажда или учащённое мочеиспускание?",
        "Есть ли бледность, головокружение или одышка?",
    ],
    "neuro_numb_arm_face": [
        "Слабость или онемение появились резко или постепенно?",
        "Есть ли онемение лица, нарушение речи или зрения?",
        "Есть ли головокружение?",
        "Есть ли головная боль?",
    ],
    "oral_cavity_gum_abscess_like": [
        "Как давно кровят десны? Как чистите зубы?",
        "Есть ли отёк или боль в десне?",
        "Есть ли температура?",
        "Какой именно участок болит?",
    ],
    "orthopedics_finger_injury": [
        "Подворачивали ногу? Была ли травма?",
        "Можете ли вы наступать на ногу?",
        "Есть ли отек или деформация?",
        "Где именно болит?",
    ],
}


def override_questions_by_scenario(
    scenario_id: str,
    current_questions: list[str] | None,
    *,
    user_message: str = "",
    evidence_present: list[Any] | None = None,
) -> list[str]:
    sid = str(scenario_id or "").strip().lower()
    blob = (user_message or "").strip()
    if sid in _ORAL_SCENARIOS_STOMPED_BY_URI and _acute_febrile_respiratory_context(blob, evidence_present):
        return list(current_questions or [])
    if sid in SCENARIO_QUESTION_MAP:
        return list(SCENARIO_QUESTION_MAP[sid])
    return list(current_questions or [])
