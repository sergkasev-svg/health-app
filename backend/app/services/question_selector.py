from __future__ import annotations

from typing import Any


QUESTION_BANK = {
    "cardio": [
        "Есть ли боль в груди?",
        "Есть ли одышка?",
        "Какое давление?",
        "Какой пульс?",
        "Есть ли перебои в сердце?",
    ],
    "urinary": [
        "Есть ли жжение или рези при мочеиспускании?",
        "Есть ли частое мочеиспускание?",
        "Есть ли боль в пояснице или в боку?",
        "Есть ли температура, озноб или кровь в моче?",
    ],
    "fatigue_deficiency": [
        "Как давно беспокоит усталость или слабость?",
        "Есть ли бледность, головокружение или одышка?",
        "Есть ли мутная голова?",
        "Есть ли гемоглобин, ферритин, витамин D или B12?",
    ],
    "respiratory": [
        "Есть ли температура?",
        "Есть ли кашель?",
        "Есть ли мокрота?",
        "Есть ли боль в горле?",
        "Есть ли насморк?",
        "Есть ли одышка?",
    ],
    "oral_cavity": [
        "Какой именно зуб или участок болит?",
        "Есть ли отек десны или щеки?",
        "Есть ли температура или гной?",
        "Больно ли открывать рот или глотать?",
    ],
    "neuro": [
        "Головная боль началась внезапно?",
        "Есть ли тошнота или рвота?",
        "Есть ли светобоязнь?",
        "Есть ли онемение, слабость, нарушение речи или зрения?",
        "Есть ли головокружение?",
    ],
    "gastro": [
        "Где именно болит живот?",
        "Есть ли тошнота или рвота?",
        "Есть ли понос?",
        "Есть ли кровь в стуле или черный стул?",
        "Есть ли температура?",
    ],
    "allergy_skin": [
        "Есть ли сыпь?",
        "Есть ли зуд?",
        "Есть ли отек губ или языка?",
        "Есть ли одышка?",
        "После чего это появилось?",
    ],
    "knee": [
        "Можете ли вы наступать на ногу?",
        "Есть ли отек колена?",
        "Колено заклинивает?",
    ],
    "ankle": [
        "Подворачивали ногу?",
        "Можете ли вы наступать на ногу?",
        "Есть ли отек?",
    ],
    "shoulder": [
        "Больно ли поднимать руку?",
        "Была ли травма?",
    ],
    "back": [
        "Боль отдает в ногу?",
        "Есть ли онемение, слабость или нарушение мочеиспускания?",
    ],
    "generic": [
        "Как давно появились симптомы?",
        "Есть ли температура?",
        "Что усиливает симптомы?",
    ],
}


def _looks_like_febrile_respiratory_text(text: str) -> bool:
    t = (text or "").lower()
    has_fever = any(k in t for k in ("температур", "39", "38", "лихорад", "жар"))
    resp_hits = sum(
        1
        for k in ("каш", "мокрот", "сопл", "насморк", "горл", "орви", "простуд", "дых")
        if k in t
    )
    return has_fever and resp_hits >= 2


def _scope_from_evidence(present: set[str]) -> str:
    if {"oral_pain", "oral_swelling", "oral_trismus_swallow", "oral_pus", "oral_candidiasis_like", "dry_mouth"} & present:
        return "oral_cavity"
    resp_ev = {"cough", "sore_throat", "runny_nose", "dyspnea", "sputum"} & present
    # При жаре + ЛОР/кашле не уводить область в «невро» только из‑за головной боли (типично для ОРВИ).
    if "fever" in present and (len(resp_ev) >= 2 or (len(resp_ev) >= 1 and "headache" in present)):
        return "respiratory"
    if {"headache", "photophobia", "neurologic_deficit", "sudden_onset", "dizziness_like"} & present:
        return "neuro"
    if {"burning_urination", "urinary_frequency", "flank_pain", "hematuria", "urinary_specific"} & present:
        return "urinary"
    if {"fatigue", "anemia_features", "labs_discussed"} & present:
        return "fatigue_deficiency"
    if {"cough", "sore_throat", "runny_nose", "dyspnea", "sputum"} & present:
        return "respiratory"
    if {"abdominal_pain", "vomiting", "diarrhea", "blood_in_stool"} & present:
        return "gastro"
    if {"chest_pain", "palpitations", "high_bp_context"} & present:
        return "cardio"
    if {"rash", "itching", "angioedema_risk", "allergy_respiratory_risk"} & present:
        return "allergy_skin"
    if "knee_pain" in present:
        return "knee"
    if "ankle_pain" in present:
        return "ankle"
    if "shoulder_pain" in present:
        return "shoulder"
    if "back_pain" in present:
        return "back"
    return "generic"


def select_best_questions(
    known_present: set[str] | list[str],
    known_absent: set[str] | list[str],
    asked_question_ids: set[str] | list[str] | None = None,
    max_n: int = 1,
    complaint_hint: str = "",
    protocol_questions: list[str] | None = None,
) -> list[dict[str, Any]]:
    present = {str(x).strip() for x in (known_present or []) if str(x).strip()}
    scope = _scope_from_evidence(present)
    texts = list(QUESTION_BANK.get(scope, QUESTION_BANK["generic"]))

    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for i, text in enumerate(texts):
        s = str(text).strip()
        if not s or s in seen:
            continue
        out.append({"id": f"{scope}_{i}", "scope": scope, "text": s, "maps_to": f"{scope}_{i}"})
        seen.add(s)
        if len(out) >= max_n:
            break

    for i, pq in enumerate(protocol_questions or []):
        s = str(pq).strip()
        if not s or s in seen:
            continue
        out.append({"id": f"protocol_{i}", "scope": scope, "text": s, "maps_to": f"protocol_{i}"})
        seen.add(s)
        if len(out) >= max_n:
            break

    return out[:max_n]


def select_best_questions_from_case_state(case_state: dict[str, Any], max_n: int = 1) -> list[dict[str, Any]]:
    context_blob = " ".join(
        [
            str(case_state.get("conversation_context") or ""),
            str(case_state.get("normalized_text") or ""),
            str(case_state.get("chief_complaint") or ""),
            str(case_state.get("complaint_hint") or ""),
        ]
    ).strip()
    if _looks_like_febrile_respiratory_text(context_blob):
        out: list[dict[str, Any]] = []
        for i, text in enumerate(QUESTION_BANK.get("respiratory", [])):
            s = str(text).strip()
            if not s:
                continue
            out.append({"id": f"respiratory_{i}", "scope": "respiratory", "text": s, "maps_to": f"respiratory_{i}"})
            if len(out) >= max_n:
                break
        if out:
            return out[:max_n]

    return select_best_questions(
        known_present=case_state.get("evidence_present") or [],
        known_absent=case_state.get("evidence_absent") or [],
        asked_question_ids=case_state.get("asked_question_ids") or case_state.get("asked_questions") or [],
        max_n=max_n,
        complaint_hint=str(case_state.get("complaint_hint") or ""),
        protocol_questions=case_state.get("protocol_questions") or [],
    )
