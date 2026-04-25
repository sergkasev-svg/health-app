"""
Microbiome Engine v1.1 — скоринг по осям кишечник–организм.
RAG/scoring/продуктовый слой: gut_muscle, gut_brain, gut_immune, gut_skin.
Не диагноз; научно-осторожные инсайты и рекомендации.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class MicrobiomeAxisResult:
    axis: str
    score: int
    level: str
    triggered_by: List[str] = field(default_factory=list)
    insights: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    cta: str | None = None


def _contains_any(text: str, terms: List[str]) -> List[str]:
    text_l = (text or "").lower()
    return [t for t in terms if t.lower() in text_l]


def _score_bucket(score: int) -> str:
    if score <= 2:
        return "low"
    if score <= 5:
        return "moderate"
    return "high"


def _bool(v: Any) -> bool:
    return bool(v)


def build_microbiome_payload_from_message(
    message: str,
    profile: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Собирает payload для calc_microbiome_axes из сообщения пользователя и профиля.
    Булевы поля выводятся по ключевым словам в тексте.
    """
    profile = profile or {}
    try:
        age = int(profile.get("age") or 0)
    except (TypeError, ValueError):
        age = 0
    text = (message or "").strip().lower()
    return {
        "chief_complaint": message or "",
        "history_text": "",
        "symptoms": [],
        "age": age,
        "low_activity": profile.get("low_activity") if isinstance(profile.get("low_activity"), bool) else None,
        "fatigue": any(k in text for k in ("слабость", "усталость", "утомляемость", "нет сил", "сил нет")),
        "poor_sleep": any(k in text for k in ("плохой сон", "бессонница", "не сплю", "плохо сплю")),
        "gi_symptoms": any(k in text for k in ("живот", "кишечник", "дискомфорт в животе", "вздутие", "запор", "диарея")),
        "recent_antibiotics": any(k in text for k in ("антибиотик", "после антибиотиков")),
        "high_sugar_diet": False,
        "low_fiber_diet": False,
        "chronic_stress": any(k in text for k in ("стресс", "тревога", "подавлен", "депрессия")),
        "protein_deficit_risk": False,
        "recurrent_infections": any(k in text for k in ("часто болею", "слабый иммунитет")),
        "inflammatory_skin": any(k in text for k in ("акне", "сыпь", "дерматит", "кожа")),
        "unintended_weight_loss": any(k in text for k in ("похудел", "потеря веса", "снижение веса")),
    }


def calc_microbiome_axes(payload: Dict[str, Any]) -> List[MicrobiomeAxisResult]:
    symptoms_text = " ".join(payload.get("symptoms", []) or [])
    free_text = " ".join(
        [
            payload.get("chief_complaint", "") or "",
            payload.get("history_text", "") or "",
            symptoms_text,
        ]
    ).strip()

    age = int(payload.get("age") or 0)
    low_activity = _bool(payload.get("low_activity"))
    fatigue = _bool(payload.get("fatigue"))
    poor_sleep = _bool(payload.get("poor_sleep"))
    gi_symptoms = _bool(payload.get("gi_symptoms"))
    recent_antibiotics = _bool(payload.get("recent_antibiotics"))
    high_sugar_diet = _bool(payload.get("high_sugar_diet"))
    low_fiber_diet = _bool(payload.get("low_fiber_diet"))
    chronic_stress = _bool(payload.get("chronic_stress"))
    protein_deficit_risk = _bool(payload.get("protein_deficit_risk"))
    recurrent_infections = _bool(payload.get("recurrent_infections"))
    inflammatory_skin = _bool(payload.get("inflammatory_skin"))
    unintended_weight_loss = _bool(payload.get("unintended_weight_loss"))

    results: List[MicrobiomeAxisResult] = []

    # gut_muscle
    muscle_terms = [
        "слабость", "нет сил", "утомляемость", "снижение силы",
        "саркопения", "плохо восстанавливаюсь"
    ]
    muscle_hits = _contains_any(free_text, muscle_terms)
    if muscle_hits or age > 50 or low_activity or fatigue:
        score = 0
        score += 2 if age > 50 else 0
        score += 2 if low_activity else 0
        score += 2 if fatigue else 0
        score += 1 if protein_deficit_risk else 0
        score += 1 if unintended_weight_loss else 0
        level = _score_bucket(score)
        results.append(
            MicrobiomeAxisResult(
                axis="gut_muscle",
                score=score,
                level=level,
                triggered_by=muscle_hits,
                insights=[
                    "Есть данные, что отдельные кишечные бактерии связаны с мышечной силой.",
                    "Roseburia inulinivorans — перспективный кандидат оси кишечник-мышцы, но это не доказанная терапия для человека."
                ],
                recommendations=[
                    "Силовые нагрузки 2–3 раза в неделю по переносимости.",
                    "Оценить белок в рационе; ориентир часто 1.2–1.6 г/кг/сут, если нет противопоказаний и врач не ограничивал.",
                    "Повысить разнообразие пищевых волокон и продуктов, поддерживающих микробиом.",
                    "При выраженной слабости, потере веса или падениях — очная оценка врача."
                ],
                cta="Получить персональный план силы, восстановления и поддержки микробиома"
            )
        )

    # gut_brain
    brain_terms = [
        "тревога", "депрессия", "подавленность", "стресс",
        "раздражительность", "плохой сон", "бессонница"
    ]
    brain_hits = _contains_any(free_text, brain_terms)
    if brain_hits or chronic_stress or poor_sleep:
        score = 0
        score += 2 if chronic_stress else 0
        score += 2 if poor_sleep else 0
        score += 1 if gi_symptoms else 0
        score += 1 if recent_antibiotics else 0
        score += 1 if high_sugar_diet else 0
        level = _score_bucket(score)
        results.append(
            MicrobiomeAxisResult(
                axis="gut_brain",
                score=score,
                level=level,
                triggered_by=brain_hits,
                insights=[
                    "Ось кишечник-мозг активно изучается; есть данные о связи микробиома со стресс-ответом и настроением.",
                    "Психобиотические эффекты у людей пока ограничены и не заменяют лечение депрессии или тревожных расстройств."
                ],
                recommendations=[
                    "Нормализовать сон и режим питания.",
                    "Увеличить долю цельных продуктов и клетчатки, сократить ультрапереработанную пищу.",
                    "При выраженной тревоге, депрессии или суицидальных мыслях — срочно обратиться за медицинской помощью."
                ],
                cta="Получить персональный план поддержки оси кишечник-мозг"
            )
        )

    # gut_immune
    immune_terms = ["часто болею", "воспаление", "слабый иммунитет", "после антибиотиков"]
    immune_hits = _contains_any(free_text, immune_terms)
    if immune_hits or recurrent_infections or recent_antibiotics or gi_symptoms:
        score = 0
        score += 2 if recent_antibiotics else 0
        score += 2 if recurrent_infections else 0
        score += 1 if low_fiber_diet else 0
        score += 1 if gi_symptoms else 0
        level = _score_bucket(score)
        results.append(
            MicrobiomeAxisResult(
                axis="gut_immune",
                score=score,
                level=level,
                triggered_by=immune_hits,
                insights=[
                    "Состояние кишечного барьера и состав микробиома связаны с иммунной регуляцией.",
                    "Akkermansia muciniphila и Faecalibacterium prausnitzii часто рассматриваются как перспективные бактерии для barrier/anti-inflammatory профиля."
                ],
                recommendations=[
                    "Увеличить пищевые волокна постепенно и по переносимости.",
                    "После антибиотиков уделить внимание восстановлению рациона и кишечной переносимости.",
                    "При повторных инфекциях или высокой температуре — очная диагностика обязательна."
                ],
                cta="Получить план восстановления кишечного барьера"
            )
        )

    # gut_skin
    skin_terms = ["акне", "сыпь", "дерматит", "кожа", "обострения после еды"]
    skin_hits = _contains_any(free_text, skin_terms)
    if skin_hits or inflammatory_skin:
        score = 0
        score += 2 if inflammatory_skin else 0
        score += 1 if high_sugar_diet else 0
        score += 1 if gi_symptoms else 0
        score += 1 if recent_antibiotics else 0
        level = _score_bucket(score)
        results.append(
            MicrobiomeAxisResult(
                axis="gut_skin",
                score=score,
                level=level,
                triggered_by=skin_hits,
                insights=[
                    "Ось кишечник-кожа — перспективное направление; состав микробиома может быть связан с воспалительными кожными состояниями.",
                    "Это не означает, что пробиотик сам по себе лечит акне или дерматит."
                ],
                recommendations=[
                    "Снизить избыток сахара и ультрапереработанной еды.",
                    "Отслеживать связь кожи с ЖКТ-симптомами и рационом.",
                    "При выраженной сыпи, мокнутии, боли или инфекции кожи — очно к врачу."
                ],
                cta="Получить план питания и поддержки оси кишечник-кожа"
            )
        )

    return results
