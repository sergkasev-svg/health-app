"""Точка встраивания P1/P2 в ClinicalCoreResult (без побочных эффектов при пустом тексте)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.clinical_engine.contracts import ClinicalCoreResult
from app.services.clinical_engine.clinical_rules.engine import ClinicalRulesEngine
from app.services.clinical_engine.clinical_rules.p2_synthesis.pattern_ranker import rank_patterns
from app.services.clinical_engine.clinical_rules.p2_synthesis.summary_builder import (
    _risks_from_core,
    build_summary_structured_from_core,
)
from app.services.clinical_engine.clinical_rules.value_enrichment import enrich_values_for_rules


def _patient_age_years(patient_meta: Dict[str, Any]) -> Optional[int]:
    a = patient_meta.get("age_years")
    if a is None:
        return None
    try:
        return int(float(a))
    except (TypeError, ValueError):
        return None


def apply_clinical_rules_to_core(
    core: ClinicalCoreResult,
    extracted_text: str,
    patient_meta: Optional[Dict[str, Any]] = None,
) -> ClinicalCoreResult:
    """
    Обогащает core клиническими паттернами и при наличии ≥1 P1 — интегрированным summary.
    Если extracted_text пуст или паттернов нет — возвращает core без изменений.
    """
    if not (extracted_text or "").strip():
        return core

    enriched = enrich_values_for_rules(dict(core.normalized_values or {}), extracted_text)
    meta = dict(patient_meta or {})
    patterns = ClinicalRulesEngine().run(
        enriched,
        list(core.final_findings or []),
        meta,
    )
    if not patterns:
        return core

    risks = _risks_from_core(core)
    ranked = rank_patterns(patterns, risks=risks, patient_age=_patient_age_years(meta))

    if not any(p.level == "P1" for p in ranked):
        return core.model_copy(update={"clinical_patterns": ranked})

    out = build_summary_structured_from_core(core, ranked, meta)
    return core.model_copy(
        update={
            "clinical_patterns": ranked,
            "summary": out.main_conclusion,
            "pattern_summary_headline": out.ui_headline,
            "pattern_main_conclusion": out.main_conclusion,
            "pattern_attention_items": list(out.attention_items),
            "pattern_next_steps_items": list(out.next_steps_items),
        }
    )
