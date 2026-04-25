"""
Реестр pathway: сопоставление решения с шаблонами планов (железо, щитовидка, аллергия, инфекция).
Каждый matcher возвращает (matched: bool, pathway_id: str).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Типы: decision_output — DecisionOutput, context — dict с structured_lab_report, lab_rows, symptoms; memory — MikhailSessionMemory или None


def _get_topics(context: Optional[Dict[str, Any]]) -> List[str]:
    report = (context or {}).get("structured_lab_report") or {}
    return list((report.get("hidden_debug") or report.get("debug") or {}).get("topics") or [])


def _get_supports(context: Optional[Dict[str, Any]]) -> List[str]:
    report = (context or {}).get("structured_lab_report") or {}
    return list((report.get("hidden_debug") or report.get("debug") or {}).get("supports") or [])


def _lab_has_marker(lab_rows: List[Dict], names: List[str]) -> bool:
    if not lab_rows:
        return False
    lower_names = [n.lower() for n in names]
    for row in lab_rows:
        title = (row.get("title") or row.get("marker_name") or row.get("name") or "").lower()
        if any(n in title or title in n for n in lower_names):
            return True
    return False


def _lab_value_low(row: Dict, ref_key: str = "ref_low") -> bool:
    v = row.get("value")
    ref = row.get(ref_key)
    if v is None or ref is None:
        return False
    try:
        return float(v) < float(ref)
    except (TypeError, ValueError):
        return False


def _lab_value_high(row: Dict, ref_key: str = "ref_high") -> bool:
    v = row.get("value")
    ref = row.get(ref_key)
    if v is None or ref is None:
        return False
    try:
        return float(v) > float(ref)
    except (TypeError, ValueError):
        return False


def match_iron_deficiency_pattern(
    decision_output: Any,
    orchestrator_context: Optional[Dict[str, Any]],
    memory: Optional[Any],
) -> Tuple[bool, str]:
    """Hb borderline/low, MCH low, reticulocytes low -> iron_deficiency_pattern."""
    context = orchestrator_context or {}
    topics = _get_topics(context)
    if "iron_deficiency" in topics or "anemia_pattern" in topics:
        return (True, "iron_deficiency_pattern")
    lab_rows = context.get("lab_rows") or []
    if not lab_rows:
        return (False, "")
    has_hb = _lab_has_marker(lab_rows, ["гемоглобин", "hemoglobin", "hgb", "hb"])
    has_mch = _lab_has_marker(lab_rows, ["mch", "среднее содержание гемоглобина"])
    has_retic = _lab_has_marker(lab_rows, ["ретикулоцит", "reticulocyte"])
    for row in lab_rows:
        title = (row.get("title") or row.get("marker_name") or "").lower()
        if "гемоглобин" in title or "hemoglobin" in title or "hgb" in title:
            if _lab_value_low(row) or (row.get("value") is not None and row.get("ref_low") and float(row.get("value", 0)) < float(row.get("ref_low", 0)) * 1.05):
                if has_mch or has_retic:
                    return (True, "iron_deficiency_pattern")
        if "mch" in title and _lab_value_low(row):
            if has_hb:
                return (True, "iron_deficiency_pattern")
    return (False, "")


def match_hypothyroid_pattern(
    decision_output: Any,
    orchestrator_context: Optional[Dict[str, Any]],
    memory: Optional[Any],
) -> Tuple[bool, str]:
    """TSH high, free T4 low or normal -> thyroid_hypothyroid_pattern."""
    context = orchestrator_context or {}
    topics = _get_topics(context)
    if "thyroid_hypo" in topics:
        return (True, "thyroid_hypothyroid_pattern")
    lab_rows = context.get("lab_rows") or []
    for row in lab_rows:
        title = (row.get("title") or row.get("marker_name") or "").lower()
        if "tsh" in title or "тиреотроп" in title:
            if _lab_value_high(row):
                return (True, "thyroid_hypothyroid_pattern")
    return (False, "")


def match_thyrotoxicosis_pattern(
    decision_output: Any,
    orchestrator_context: Optional[Dict[str, Any]],
    memory: Optional[Any],
) -> Tuple[bool, str]:
    """TSH low, free T4 or T3 high -> thyroid_thyrotoxicosis_pattern."""
    context = orchestrator_context or {}
    topics = _get_topics(context)
    if "thyroid_hyper" in topics:
        return (True, "thyroid_thyrotoxicosis_pattern")
    lab_rows = context.get("lab_rows") or []
    tsh_low = False
    ft4_high = False
    for row in lab_rows:
        title = (row.get("title") or row.get("marker_name") or "").lower()
        if "tsh" in title or "тиреотроп" in title:
            if _lab_value_low(row):
                tsh_low = True
        if "free t4" in title or "свободный т4" in title or "ft4" in title or "т4 св" in title:
            if _lab_value_high(row):
                ft4_high = True
        if "т3" in title or "t3" in title:
            if _lab_value_high(row):
                ft4_high = True
    if tsh_low and ft4_high:
        return (True, "thyroid_thyrotoxicosis_pattern")
    return (False, "")


def match_mild_allergy_pattern(
    decision_output: Any,
    orchestrator_context: Optional[Dict[str, Any]],
    memory: Optional[Any],
) -> Tuple[bool, str]:
    """Mild eosinophilia + relevant symptoms -> mild_allergy_pattern."""
    context = orchestrator_context or {}
    topics = _get_topics(context)
    if "possible_allergy" in topics or "allergy_pattern" in topics:
        return (True, "mild_allergy_pattern")
    lab_rows = context.get("lab_rows") or []
    _msg = getattr(decision_output, "final_user_message", None) if decision_output else None
    if _msg is None and isinstance(decision_output, dict):
        _msg = decision_output.get("final_user_message")
    symptoms = (context.get("normalized_symptoms") or []) + [str(_msg or "")[:200]]
    symptoms_str = " ".join(str(s).lower() for s in symptoms)
    allergy_keywords = ["зуд", "сыпь", "насморк", "аллерг", "эозинофил", "крапивница"]
    if not any(k in symptoms_str for k in allergy_keywords):
        return (False, "")
    for row in lab_rows:
        title = (row.get("title") or row.get("marker_name") or "").lower()
        if "эозинофил" in title or "eosinophil" in title:
            return (True, "mild_allergy_pattern")
    return (False, "")


def match_mild_infection_pattern(
    decision_output: Any,
    orchestrator_context: Optional[Dict[str, Any]],
    memory: Optional[Any],
) -> Tuple[bool, str]:
    """WBC/neutrophils elevated, fever symptoms -> mild_infection_pattern."""
    context = orchestrator_context or {}
    topics = _get_topics(context)
    if "infection_pattern" in topics or "inflammation_pattern" in topics:
        return (True, "mild_infection_pattern")
    lab_rows = context.get("lab_rows") or []
    symptoms = context.get("normalized_symptoms") or []
    symptoms_str = " ".join(str(s).lower() for s in symptoms)
    if "температура" not in symptoms_str and "лихорадка" not in symptoms_str and "жар" not in symptoms_str:
        return (False, "")
    for row in lab_rows:
        title = (row.get("title") or row.get("marker_name") or "").lower()
        if "лейкоцит" in title or "wbc" in title or "нейтрофил" in title:
            if _lab_value_high(row):
                return (True, "mild_infection_pattern")
    return (False, "")


PATHWAY_MATCHERS = [
    match_iron_deficiency_pattern,
    match_hypothyroid_pattern,
    match_thyrotoxicosis_pattern,
    match_mild_allergy_pattern,
    match_mild_infection_pattern,
]


def match_pathway(
    decision_output: Any,
    orchestrator_context: Optional[Dict[str, Any]],
    memory: Optional[Any],
) -> Tuple[bool, str]:
    """Первый сработавший matcher возвращает (True, pathway_id). Иначе (False, "")."""
    for matcher in PATHWAY_MATCHERS:
        ok, pathway_id = matcher(decision_output, orchestrator_context, memory)
        if ok:
            return (True, pathway_id)
    return (False, "")
