"""
Concierge action sequence engine:
anamnesis -> differential diagnosis -> recommendations pipeline.
Uses disease catalog (auto 300+ when available).
"""
import json
import re
from pathlib import Path
from typing import Any

from app.services.clinical_profiles import search_clinical_profiles


_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_CATALOG_AUTO = _PROJECT_ROOT / "medical_knowledge" / "diseases" / "disease_catalog_auto_300_plus.json"
_CATALOG_SEED = _PROJECT_ROOT / "medical_knowledge" / "diseases" / "disease_catalog_seed_50.json"

_STOPWORDS = {
    "и", "в", "во", "на", "с", "со", "к", "по", "за", "от", "до", "у", "о", "об",
    "что", "как", "где", "когда", "почему", "мне", "меня", "мой", "моя", "мои",
    "this", "that", "with", "from", "for", "the", "and", "или", "но", "же",
}


def _load_catalog() -> list[dict[str, Any]]:
    for path in (_CATALOG_AUTO, _CATALOG_SEED):
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            items = payload.get("items") if isinstance(payload, dict) else None
            if isinstance(items, list):
                return [x for x in items if isinstance(x, dict)]
    return []


CATALOG_ITEMS = _load_catalog()


def _tokenize(text: str) -> list[str]:
    s = re.sub(r"[^\w\sа-яёa-z0-9]", " ", (text or "").lower())
    return [w for w in s.split() if len(w) >= 3 and w not in _STOPWORDS]


def _match_diagnoses(user_message: str, max_items: int = 3) -> list[dict[str, Any]]:
    profile_hits = search_clinical_profiles(user_message, top_k=max_items)
    if profile_hits:
        out = []
        for i, p in enumerate(profile_hits):
            out.append(
                {
                    "name": p.get("name") or "",
                    "icd10": p.get("icd10") or "",
                    "category": p.get("category") or "Общая медицина",
                    "confidence": round(max(0.6, 0.9 - (i * 0.1)), 2),
                }
            )
        return out[:max_items]

    words = set(_tokenize(user_message))
    if not words or not CATALOG_ITEMS:
        return []

    scored: list[tuple[float, dict[str, Any]]] = []
    for it in CATALOG_ITEMS:
        name = str(it.get("name") or "")
        desc = str(it.get("description") or "")
        category = str(it.get("category") or "")
        hay = f"{name} {desc} {category}".lower()
        hits = sum(1 for w in words if w in hay)
        if hits <= 0:
            continue
        # Title match is stronger than description-only match.
        name_hits = sum(1 for w in words if w in name.lower())
        score = hits + (name_hits * 1.5)
        scored.append((score, it))

    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[dict[str, Any]] = []
    for score, it in scored[:max_items]:
        out.append(
            {
                "name": it.get("name") or "",
                "icd10": it.get("icd10") or "",
                "category": it.get("category") or "Общая медицина",
                "confidence": round(min(0.95, 0.45 + score / 12.0), 2),
            }
        )
    return out


def _anamnesis_checklist(intent: str) -> list[str]:
    base = [
        "Уточнить начало и длительность симптомов.",
        "Уточнить тяжесть, динамику и триггеры.",
        "Проверить сопутствующие заболевания и текущие препараты.",
        "Проверить аллергии и непереносимости.",
        "Проверить красные флаги и показания к срочной помощи.",
    ]
    if intent == "nutrition":
        base.extend([
            "Оценить режим питания, воду, дефициты и ограничения.",
            "Сопоставить рацион с жалобами и лабораторными данными.",
        ])
    elif intent == "fitness":
        base.extend([
            "Оценить тип, частоту и переносимость нагрузок.",
            "Проверить риски по сердцу/суставам перед усилением тренировок.",
        ])
    else:
        base.extend([
            "Собрать органоспецифичные симптомы для диф-диагноза.",
            "Определить, какие анализы критичны для подтверждения гипотез.",
        ])
    return base


def _build_treatment_block(structured: dict[str, Any], has_lab_data: bool) -> dict[str, Any]:
    exams = list(structured.get("exam_recommendations") or [])
    hypotheses = list(structured.get("hypotheses") or [])
    nutrition = list(structured.get("nutrition_advice") or [])
    activity = list(structured.get("activity_advice") or [])

    meds = []
    for line in hypotheses + exams:
        low = str(line).lower()
        if any(k in low for k in ["препарат", "лекар", "терап", "доза", "антибиот", "ибупроф", "парацетам"]):
            meds.append(str(line))
    if not meds:
        meds.append("Подбор лекарственной терапии только после подтверждения рабочей гипотезы и противопоказаний.")

    diagnostics_goal = (
        "Есть лабораторные данные: уточнить диагноз и скорректировать план."
        if has_lab_data else
        "Нет лабораторных данных: сначала подтвердить гипотезу анализами/осмотром."
    )
    return {
        "diagnostics_goal": diagnostics_goal,
        "medications": meds[:6],
        "nutrition": nutrition[:8],
        "activity": activity[:8],
    }


def build_concierge_action_sequence(
    user_message: str,
    symptom_payload: dict[str, Any],
    structured: dict[str, Any],
    suggested_questions: list[str],
    has_lab_data: bool = False,
) -> dict[str, Any]:
    """
    Builds deterministic concierge script to reach actionable recommendations.
    """
    intent = (symptom_payload or {}).get("intent") or "general"
    diagnoses = _match_diagnoses(user_message, max_items=3)
    checklist = _anamnesis_checklist(intent)
    profile_hits = search_clinical_profiles(user_message, top_k=1)
    if profile_hits:
        for q in (profile_hits[0].get("anamnesis") or [])[:3]:
            if q not in checklist:
                checklist.append(q)
    treatment = _build_treatment_block(structured or {}, has_lab_data=has_lab_data)

    phases = [
        {
            "phase": 1,
            "name": "Сбор анамнеза",
            "goal": "Собрать необходимую и достаточную информацию по жалобе.",
            "actions": checklist,
            "questions_to_ask": (suggested_questions or [])[:5],
            "done_when": "Есть ключевые симптомы, длительность, тяжесть, фон, красные флаги.",
        },
        {
            "phase": 2,
            "name": "Установка наиболее точного рабочего диагноза",
            "goal": "Сформировать и ранжировать дифференциальные гипотезы.",
            "actions": [
                "Сопоставить жалобы с каталогом заболеваний и контекстом знаний.",
                "Отсечь нерелевантные варианты по клиническим признакам.",
                "Выделить 1-3 наиболее вероятные гипотезы с ICD-10.",
            ],
            "candidate_diagnoses": diagnoses,
            "done_when": "Есть ранжированный список гипотез и план подтверждения.",
        },
        {
            "phase": 3,
            "name": "Воздействие и лечение",
            "goal": "Сформировать персонализированные рекомендации до получения результата.",
            "actions": [
                "Определить диагностическую цель и необходимые обследования.",
                "Сформировать рекомендации по лекарственной терапии (если уместно).",
                "Добавить блоки по питанию и физической активности.",
                "Сформировать критерии контроля состояния и повторной оценки.",
            ],
            "treatment_plan": treatment,
            "done_when": "Пользователь получил понятный план действий и критерии контроля.",
        },
    ]

    return {
        "engine": "concierge_action_sequence_v1",
        "status": "in_progress" if (suggested_questions or []) else "ready_for_recommendations",
        "current_phase": "Сбор анамнеза" if (suggested_questions or []) else "Воздействие и лечение",
        "target_result": "Получение релевантных рекомендаций по лечению, питанию и активности.",
        "phases": phases,
        "red_flags": list(structured.get("red_flags") or []),
        "disclaimer": structured.get("disclaimer") or (
            "Информация носит справочный характер и не заменяет консультацию врача."
        ),
    }

