"""
Конфигурация Microbiome Engine v1: оси, сущности, триггеры.
"""
from __future__ import annotations

MICROBIOME_ENGINE_VERSION = "1.0"
AXES = ["gut_muscle", "gut_brain", "gut_immune", "gut_skin"]
ENTRY_POINTS = ["symptoms", "labs", "lifestyle"]

# Сущности (минимально достаточный набор)
ENTITIES = [
    {
        "id": "roseburia_inulinivorans",
        "axis": ["gut_muscle"],
        "effect": "muscle_strength_association",
        "evidence": "human_association + animal_support",
        "safe_claim": "связана с мышечной силой",
    },
    {
        "id": "faecalibacterium_prausnitzii",
        "axis": ["gut_immune", "gut_brain"],
        "effect": "anti_inflammatory",
        "safe_claim": "связана с противовоспалительным эффектом",
    },
    {
        "id": "akkermansia_muciniphila",
        "axis": ["gut_immune", "gut_skin"],
        "effect": "barrier_function",
        "safe_claim": "связана с целостностью кишечного барьера",
    },
    {
        "id": "bifidobacterium_longum",
        "axis": ["gut_brain"],
        "effect": "mood_support",
        "safe_claim": "может быть связана с настроением",
    },
    {
        "id": "bifidobacterium_breve_ccfm1025",
        "axis": ["gut_brain"],
        "effect": "psychobiotic_candidate",
        "evidence": "rct_signal_depressive_symptoms_gi",
        "safe_claim": "перспективный психобиотический кандидат; РКИ-сигнал по симптомам депрессии и ЖКТ; не заменяет стандартное лечение",
    },
    {
        "id": "lactobacillus_rhamnosus",
        "axis": ["gut_brain"],
        "effect": "stress_response",
        "safe_claim": "может влиять на стресс-ответ",
    },
]

# Триггеры по осям (ключевые слова в симптомах/тексте)
AXIS_TRIGGERS = {
    "gut_muscle": [
        "слабость",
        "усталость",
        "утомляемость",
        "снижение силы",
        "нет сил",
        "сил нет",
        "мышечная слабость",
        "старею",
        "восстановление плохое",
    ],
    "gut_brain": [
        "тревога",
        "депрессия",
        "плохой сон",
        "бессонница",
        "раздражительность",
        "настроение",
        "стресс",
        "тревожность",
    ],
    "gut_immune": [
        "частые болезни",
        "воспален",
        "слабый иммунитет",
        "иммунитет",
        "простуда",
        "болею часто",
    ],
    "gut_skin": [
        "акне",
        "сыпь",
        "дерматит",
        "кожа",
        "прыщи",
        "экзема",
    ],
}

# Возрастной порог для gut_muscle (доп. активация)
GUT_MUSCLE_AGE_THRESHOLD = 50
