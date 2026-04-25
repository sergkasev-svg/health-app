"""
P0 rules layer: единый контракт findings → hypotheses → next_steps → risk.
Клиническая логика здесь; renderer только отображает RuleResult.
"""
from __future__ import annotations

from app.services.clinical_engine.p0_rules.contract import MarkerSnapshot, RuleResult
from app.services.clinical_engine.p0_rules.registry import P0_PROFILE_KEYS, rule_result_to_dict, run_p0_profile

__all__ = [
    "MarkerSnapshot",
    "RuleResult",
    "P0_PROFILE_KEYS",
    "run_p0_profile",
    "rule_result_to_dict",
]
