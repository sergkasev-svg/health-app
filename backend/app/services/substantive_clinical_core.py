"""
Содержательное клиническое ядро: единая точка описания того, как собирается ответ.

Не дублирует логику оркестратора — фиксирует контракт «один контекст → один синтез»
для API/клиента и внутренней документации.
"""
from __future__ import annotations

from typing import Any, Optional

from app.services.user_store import normalize_subject_id

CORE_ID = "substantive_clinical_core"
CORE_VERSION = 2

# Слои, которые участвуют в типичном ответе по жалобе/анализу (порядок — ориентир, не жёсткий DAG).
PIPELINE_LAYERS: tuple[str, ...] = (
    "symptom_and_intake",
    "red_flag_screening",
    "medical_core_selector",
    "complaint_reference",
    "indexed_medical_knowledge",
    "labs_interpretation_layers",
    "food_triggers_multidisciplinary",
    "clinical_orchestrator",
    "llm_synthesis_and_structured_output",
)


def clinical_core_envelope(
    *,
    subject_id: Optional[str] = None,
    documents_count: int = 0,
    symptom_entries_count: int = 0,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    sid = normalize_subject_id(subject_id)
    env: dict[str, Any] = {
        "id": CORE_ID,
        "version": CORE_VERSION,
        "subject_id": sid,
        "unified_context": {
            "documents_count": int(documents_count or 0),
            "symptom_entries_count": int(symptom_entries_count or 0),
        },
        "pipeline_layers": list(PIPELINE_LAYERS),
        "synthesis_model": "single_response_multi_source",
        "description_ru": (
            "Ответ собирается из симптомов и профиля, справочников (Medical Core, жалобы, индекс знаний), "
            "лабораторных и смежных слоёв, правил оркестратора и финального синтеза (LLM)."
        ),
    }
    if extra and isinstance(extra, dict):
        env["extra"] = extra
    return env


def tag_unified_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Помечает compact-snapshot как произведённый содержательным ядром."""
    out = dict(snapshot)
    out["clinical_core_id"] = CORE_ID
    out["clinical_core_version"] = CORE_VERSION
    return out
