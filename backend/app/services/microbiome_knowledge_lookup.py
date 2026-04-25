"""
Подтягивание контекста по микробиому (ось кишечник—мышцы) для запросов
про слабость, саркопению, силу, микробиом, пребиотики, бутират.
Используется в resolve_medical_context для RAG и клинических ответов.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_KNOWLEDGE_ROOT = Path(__file__).resolve().parent.parent / "knowledge"
_ENTITIES_MICROBIOME = _KNOWLEDGE_ROOT / "entities" / "microbiome"
_DOCUMENTS_DIR = _KNOWLEDGE_ROOT / "documents"

# Ключевые слова запроса, при которых подтягивать R. inulinivorans / ось кишечник—мышцы
_MICROBIOME_MUSCLE_QUERY_KEYWORDS = (
    "слабость", "сила", "саркопени", "микробиом", "микробиот", "пребиотик",
    "пробиотик", "бутират", "мышц", "мышечн", "возрастн", "хват", "vo2",
    "roseburia", "inulinivorans", "кишечник мышц", "gut muscle", "muscle strength",
)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _query_matches_microbiome_muscle(query: str) -> bool:
    if not query or not query.strip():
        return False
    low = query.strip().lower()
    return any(k in low for k in _MICROBIOME_MUSCLE_QUERY_KEYWORDS)


def get_microbiome_muscle_context(user_message: str) -> dict[str, Any] | None:
    """
    Если запрос касается слабости, саркопении, микробиома, бутирата, мышечной силы —
    возвращает контекст для ответа: сущность R. inulinivorans, эталонный текст, инструкции.
    Иначе None.
    """
    if not _query_matches_microbiome_muscle(user_message or ""):
        return None

    entity = _load_json(_ENTITIES_MICROBIOME / "roseburia_inulinivorans.json")
    doc = _load_json(_DOCUMENTS_DIR / "gut_2026_roseburia_inulinivorans_muscle_strength.json")

    reference_text = ""
    if doc:
        reference_text = (doc.get("reference_text") or "").strip()
    if not reference_text and entity:
        reference_text = (entity.get("reference_text") or entity.get("summary_ru") or "").strip()

    if not reference_text:
        return None

    return {
        "entity": entity,
        "doc_id": (doc or {}).get("doc_id", "gut_2026_roseburia_inulinivorans_muscle_strength"),
        "reference_text": reference_text,
        "usage_instructions": (
            "R. inulinivorans показывать только как перспективное направление; не обещать лечение. "
            "Отдельно давать доказанные меры: силовые тренировки, достаточный белок, коррекция дефицитов, "
            "очная оценка врача при саркопении. Микробиомные интервенции описывать как экспериментально-перспективные."
        ),
        "evidence_based_measures": [
            "силовые тренировки",
            "достаточный белок",
            "коррекция дефицитов (витамины, минералы)",
            "очная оценка врача при подозрении на саркопению",
        ],
    }
