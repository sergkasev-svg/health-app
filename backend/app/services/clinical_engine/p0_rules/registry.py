"""
Реестр P0 rule modules: profile_key → build_rule_result(values: Dict[str, MarkerSnapshot]).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Union

from app.services.clinical_engine.p0_rules.contract import MarkerSnapshot, RuleResult
from app.services.clinical_engine.p0_rules import adapters
from app.services.clinical_engine.p0_rules import biochemistry_basic
from app.services.clinical_engine.p0_rules import cbc
from app.services.clinical_engine.p0_rules import cbc_reticulocytes
from app.services.clinical_engine.p0_rules import glucose_metabolism
from app.services.clinical_engine.p0_rules import lipid_panel
from app.services.clinical_engine.p0_rules import urinalysis

BuildFn = Callable[[Dict[str, MarkerSnapshot]], RuleResult]

P0_RULE_BUILDERS: Dict[str, BuildFn] = {
    "cbc": cbc.build_rule_result,
    "cbc_with_reticulocytes": cbc_reticulocytes.build_rule_result,
    "urinalysis": urinalysis.build_rule_result,
    "biochemistry_blood": biochemistry_basic.build_rule_result,
    "lipid_panel": lipid_panel.build_rule_result,
    "glucose_metabolism": glucose_metabolism.build_rule_result,
}

P0_PROFILE_KEYS: tuple[str, ...] = tuple(sorted(P0_RULE_BUILDERS.keys()))


def _normalize_values(profile_key: str, values: Any) -> Dict[str, MarkerSnapshot]:
    if values is None:
        return {}
    if isinstance(values, dict) and values:
        if all(isinstance(v, MarkerSnapshot) for v in values.values()):
            return values
        keys = [str(k) for k in values.keys()]
        if any(k.startswith("urine_") for k in keys):
            return adapters.urinalysis_dict_to_map(values)
        return adapters.dict_floats_to_map(values)
    if isinstance(values, list):
        from app.services.lab_value_extractor import LabValue

        if values and isinstance(values[0], LabValue):
            return adapters.labvalues_to_cbc_map(values)
    return {}


def run_p0_profile(profile_key: str, values: Union[Dict[str, Any], List[Any], None]) -> Optional[RuleResult]:
    """
    Запуск правил P0.

    values:
      - Dict[str, MarkerSnapshot]
      - Dict[str, dict] — тестовые числа или словарь extract_urine_values
      - List[LabValue] — только для cbc / cbc_with_reticulocytes
    """
    builder = P0_RULE_BUILDERS.get(profile_key)
    if not builder:
        return None
    normalized = _normalize_values(profile_key, values)
    return builder(normalized)


def rule_result_to_dict(rr: RuleResult) -> Dict[str, Any]:
    return {
        "findings": rr.findings,
        "hypotheses": rr.hypotheses,
        "next_steps": rr.next_steps,
        "risk": rr.risk,
    }
