"""
P1/P2 клинические правила: паттерны → приоритет → интегрированный смысл.
Опционально включаются при наличии extracted_text в pipeline (не ломает старые вызовы).
"""
from app.services.clinical_engine.clinical_rules.engine import ClinicalRulesEngine
from app.services.clinical_engine.clinical_rules.integration import apply_clinical_rules_to_core
from app.services.clinical_engine.clinical_rules.value_enrichment import enrich_values_for_rules

__all__ = ["ClinicalRulesEngine", "enrich_values_for_rules", "apply_clinical_rules_to_core"]
