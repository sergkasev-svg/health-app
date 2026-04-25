from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_LABS_ROOT = _PROJECT_ROOT / "medical_knowledge" / "labs"
_ANALYTES_DIR = _LABS_ROOT / "analytes"
_PANELS_DIR = _LABS_ROOT / "panels"
_RULES_DIR = _LABS_ROOT / "rules"
_TERMINOLOGY_FILE = _LABS_ROOT / "terminology" / "aliases.json"
_DIAGNOSTIC_PIPELINE_FILE = _RULES_DIR / "diagnostic_pipeline.json"
_SYMPTOM_MAP_FILE = _RULES_DIR / "symptom_diagnostic_map.json"
_ANALYSIS_PACK_FILE = _RULES_DIR / "analysis_interpretation_pack.json"
_MASTER_REGISTRY_FILE = _RULES_DIR / "master_marker_registry_v1.json"
_MEDICAL_CORE_FILE = _RULES_DIR / "medical_core_v1.json"
_OUTPUT_TEMPLATE_FILE = _RULES_DIR / "medical_output_template.json"
_CASES_FILE = _LABS_ROOT / "rag" / "cases_examples.json"
_SYSTEM_PROMPT_FILE = _LABS_ROOT / "templates" / "system_prompt_medical.txt"
_REASONING_ENGINE_PROMPT_FILE = _LABS_ROOT / "templates" / "diagnostic_reasoning_engine_prompt.txt"
_RETRIEVAL_RANKING_PROMPT_FILE = _LABS_ROOT / "templates" / "medical_retrieval_ranking_prompt.txt"
_LAB_RESULT_PARSER_PROMPT_FILE = _LABS_ROOT / "templates" / "lab_result_parser_prompt.txt"
_CLINICAL_GUARDRAIL_PROMPT_FILE = _LABS_ROOT / "templates" / "clinical_safety_guardrail_prompt.txt"
_EVIDENCE_WEIGHTING_PROMPT_FILE = _LABS_ROOT / "templates" / "clinical_evidence_weighting_prompt.txt"
_ADAPTIVE_QUESTION_PROMPT_FILE = _LABS_ROOT / "templates" / "adaptive_medical_question_engine_prompt.txt"
_PROFILE_TO_PANEL_IDS: dict[str, list[str]] = {
    "оак": ["cbc_panel"],
    "биохимия": ["biochemistry_panel"],
    "гормоны": ["endocrine_hormone_panel"],
    "щитовидка": ["endocrine_hormone_panel", "endocrine_screen_panel"],
    "витамины": ["iron_panel"],
    "кардио": ["electrolyte_panel", "inflammation_panel"],
    "печень/почки": ["liver_panel", "renal_panel"],
    "глюкоза/инсулин": ["endocrine_screen_panel"],
    "гистамин/mcas-check": ["histamine_mcas_panel"],
    "воспаление": ["histamine_mcas_panel"],
    "жкт": ["abdominal_pain_panel"],
    "женское здоровье": ["endocrine_hormone_panel"],
    "мужское здоровье": ["endocrine_hormone_panel"],
}


def _load_json(path: Path, fallback: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return fallback


def _load_text(path: Path, fallback: str = "") -> str:
    try:
        if path.exists():
            return str(path.read_text(encoding="utf-8")).strip()
    except Exception:
        return fallback
    return fallback


@lru_cache(maxsize=1)
def _load_analytes() -> dict[str, dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    if not _ANALYTES_DIR.exists():
        return items
    for file_path in sorted(_ANALYTES_DIR.glob("*.json")):
        raw = _load_json(file_path, {})
        analyte_id = str(raw.get("id") or file_path.stem).strip().lower()
        if analyte_id:
            items[analyte_id] = raw
    return items


@lru_cache(maxsize=1)
def _load_panels() -> dict[str, dict[str, Any]]:
    panels: dict[str, dict[str, Any]] = {}
    if not _PANELS_DIR.exists():
        return panels
    for file_path in sorted(_PANELS_DIR.glob("*.json")):
        raw = _load_json(file_path, {})
        panel_id = str(raw.get("id") or file_path.stem).strip().lower()
        if panel_id:
            panels[panel_id] = raw
    return panels


@lru_cache(maxsize=1)
def _load_alias_map() -> dict[str, str]:
    aliases = _load_json(_TERMINOLOGY_FILE, {})
    result: dict[str, str] = {}
    if isinstance(aliases, dict):
        for alias, analyte_id in aliases.items():
            a = str(alias or "").strip().lower()
            v = str(analyte_id or "").strip().lower()
            if a and v:
                result[a] = v

    for analyte_id, payload in _load_analytes().items():
        result.setdefault(analyte_id, analyte_id)
        result.setdefault(str(payload.get("name") or "").strip().lower(), analyte_id)
        for alias in payload.get("aliases") or []:
            alias_str = str(alias or "").strip().lower()
            if alias_str:
                result.setdefault(alias_str, analyte_id)
    return result


@lru_cache(maxsize=1)
def _load_pattern_rules() -> list[dict[str, Any]]:
    payload = _load_json(_RULES_DIR / "analyte_patterns.json", [])
    return payload if isinstance(payload, list) else []


@lru_cache(maxsize=1)
def _load_red_flag_rules() -> list[dict[str, Any]]:
    payload = _load_json(_RULES_DIR / "red_flags.json", [])
    return payload if isinstance(payload, list) else []


@lru_cache(maxsize=1)
def _load_follow_up_rules() -> list[dict[str, Any]]:
    payload = _load_json(_RULES_DIR / "follow_up_rules.json", [])
    return payload if isinstance(payload, list) else []


@lru_cache(maxsize=1)
def _load_complaint_lab_links() -> list[dict[str, Any]]:
    payload = _load_json(_RULES_DIR / "complaint_lab_links.json", [])
    return payload if isinstance(payload, list) else []


@lru_cache(maxsize=1)
def _load_disease_lab_links() -> list[dict[str, Any]]:
    payload = _load_json(_RULES_DIR / "disease_lab_links.json", [])
    return payload if isinstance(payload, list) else []


@lru_cache(maxsize=1)
def _load_diagnostic_pipeline() -> dict[str, Any]:
    payload = _load_json(_DIAGNOSTIC_PIPELINE_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _load_symptom_map() -> list[dict[str, Any]]:
    payload = _load_json(_SYMPTOM_MAP_FILE, [])
    return payload if isinstance(payload, list) else []


@lru_cache(maxsize=1)
def _load_analysis_pack() -> dict[str, Any]:
    """Supplemental machine-readable interpretation pack from uploaded PDF knowledge."""
    payload = _load_json(_ANALYSIS_PACK_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _load_master_registry() -> dict[str, Any]:
    payload = _load_json(_MASTER_REGISTRY_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _load_medical_core() -> dict[str, Any]:
    payload = _load_json(_MEDICAL_CORE_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _load_output_template() -> dict[str, Any]:
    payload = _load_json(_OUTPUT_TEMPLATE_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _load_cases() -> list[dict[str, Any]]:
    payload = _load_json(_CASES_FILE, {})
    if isinstance(payload, dict):
        cases = payload.get("cases") or []
        return cases if isinstance(cases, list) else []
    return []


@lru_cache(maxsize=1)
def _load_system_prompt_addon() -> str:
    return _load_text(_SYSTEM_PROMPT_FILE, "")


@lru_cache(maxsize=1)
def _load_reasoning_engine_prompt() -> str:
    return _load_text(_REASONING_ENGINE_PROMPT_FILE, "")


@lru_cache(maxsize=1)
def _load_retrieval_ranking_prompt() -> str:
    return _load_text(_RETRIEVAL_RANKING_PROMPT_FILE, "")


@lru_cache(maxsize=1)
def _load_lab_result_parser_prompt() -> str:
    return _load_text(_LAB_RESULT_PARSER_PROMPT_FILE, "")


@lru_cache(maxsize=1)
def _load_clinical_guardrail_prompt() -> str:
    return _load_text(_CLINICAL_GUARDRAIL_PROMPT_FILE, "")


@lru_cache(maxsize=1)
def _load_evidence_weighting_prompt() -> str:
    return _load_text(_EVIDENCE_WEIGHTING_PROMPT_FILE, "")


@lru_cache(maxsize=1)
def _load_adaptive_question_prompt() -> str:
    return _load_text(_ADAPTIVE_QUESTION_PROMPT_FILE, "")


def _match_aliases(text: str) -> tuple[list[str], dict[str, list[str]]]:
    aliases = _load_alias_map()
    text_low = (text or "").lower()
    matched_ids: set[str] = set()
    matched_aliases: dict[str, list[str]] = {}
    for alias, analyte_id in aliases.items():
        if not alias:
            continue
        if len(alias) < 3:
            continue
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text_low, flags=re.IGNORECASE):
            matched_ids.add(analyte_id)
            matched_aliases.setdefault(analyte_id, []).append(alias)
    return sorted(matched_ids), matched_aliases


def _select_panels(matched_analytes: set[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for panel_id, panel in _load_panels().items():
        members = {str(x).strip().lower() for x in (panel.get("analytes") or [])}
        overlap = sorted(matched_analytes & members)
        if not overlap:
            continue
        results.append(
            {
                "id": panel_id,
                "name": panel.get("name"),
                "sample_type": panel.get("sample_type"),
                "matched_analytes": overlap,
            }
        )
    return results


def _pick_pattern_rules(matched_analytes: set[str]) -> list[dict[str, Any]]:
    if not matched_analytes:
        return []
    matched: list[dict[str, Any]] = []
    for rule in _load_pattern_rules():
        conditions = rule.get("conditions") or []
        required = {
            str(cond.get("analyte") or "").strip().lower()
            for cond in conditions
            if isinstance(cond, dict)
        }
        if not required:
            continue
        if required <= matched_analytes:
            matched.append(
                {
                    "id": rule.get("id"),
                    "name": rule.get("name"),
                    "hypotheses": rule.get("hypotheses") or [],
                    "recommend_follow_up": rule.get("recommend_follow_up") or [],
                    "red_flags": rule.get("red_flags") or [],
                }
            )
    return matched


def _pick_red_flags(matched_analytes: set[str], text: str) -> list[dict[str, Any]]:
    text_low = (text or "").lower()
    matched: list[dict[str, Any]] = []
    for item in _load_red_flag_rules():
        related = {str(x).strip().lower() for x in (item.get("related_analytes") or [])}
        triggers = [str(x or "").strip().lower() for x in (item.get("triggers") or [])]
        criteria = [str(x or "").strip().lower() for x in (item.get("criteria") or [])]
        by_analyte = bool(related and (related & matched_analytes))
        by_trigger = any(trigger and trigger in text_low for trigger in triggers)
        by_criteria = any(criterion and criterion in text_low for criterion in criteria)
        if by_analyte or by_trigger or by_criteria:
            matched.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "action": item.get("action"),
                }
            )
    return matched


def _pick_follow_up(matched_analytes: set[str], matched_patterns: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    pattern_ids = {str(x.get("id") or "").strip().lower() for x in matched_patterns if isinstance(x, dict)}
    for item in _load_follow_up_rules():
        rule_type = str(item.get("match_type") or "").strip().lower()
        values = {str(v).strip().lower() for v in (item.get("match_values") or [])}
        add_tests = [str(v).strip() for v in (item.get("suggested_follow_up") or []) if str(v).strip()]
        is_match = False
        if rule_type == "analyte" and values and (values & matched_analytes):
            is_match = True
        elif rule_type == "pattern" and values and (values & pattern_ids):
            is_match = True
        if is_match:
            result.extend(add_tests)
    dedupe: list[str] = []
    seen: set[str] = set()
    for item in result:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        dedupe.append(item)
    return dedupe


def _match_complaint_links(complaint_name: str) -> list[dict[str, Any]]:
    complaint_low = (complaint_name or "").strip().lower()
    if not complaint_low:
        return []
    out: list[dict[str, Any]] = []
    for item in _load_complaint_lab_links():
        keys = [str(x).strip().lower() for x in (item.get("complaint_keywords") or [])]
        if any(key and key in complaint_low for key in keys):
            out.append(
                {
                    "link_id": item.get("id"),
                    "suggested_panels": item.get("suggested_panels") or [],
                    "suggested_analytes": item.get("suggested_analytes") or [],
                    "rationale": item.get("rationale"),
                }
            )
    return out


def _match_disease_links(disease_names: list[str]) -> list[dict[str, Any]]:
    names_low = [str(x).strip().lower() for x in disease_names if str(x).strip()]
    if not names_low:
        return []
    out: list[dict[str, Any]] = []
    for item in _load_disease_lab_links():
        keys = [str(x).strip().lower() for x in (item.get("disease_keywords") or [])]
        if any(key and key in disease for disease in names_low for key in keys):
            out.append(
                {
                    "link_id": item.get("id"),
                    "suggested_panels": item.get("suggested_panels") or [],
                    "suggested_analytes": item.get("suggested_analytes") or [],
                    "rationale": item.get("rationale"),
                }
            )
    return out


def _match_symptoms(text: str) -> list[dict[str, Any]]:
    text_low = (text or "").strip().lower()
    if not text_low:
        return []
    out: list[dict[str, Any]] = []
    for item in _load_symptom_map():
        keys = [str(k).strip().lower() for k in (item.get("keywords") or [])]
        if not keys:
            continue
        if any(key and key in text_low for key in keys):
            out.append(
                {
                    "id": item.get("id"),
                    "name_ru": item.get("name_ru"),
                    "possible_diseases": item.get("possible_diseases") or [],
                    "recommended_tests": item.get("recommended_tests") or [],
                    "followup_questions": item.get("followup_questions") or [],
                }
            )
    return out


def _match_cases(text: str, matched_analytes: set[str]) -> list[dict[str, Any]]:
    text_low = (text or "").strip().lower()
    if not text_low:
        return []
    results: list[tuple[int, dict[str, Any]]] = []
    aliases = _load_alias_map()
    for case in _load_cases():
        score = 0
        title = str(case.get("title") or "").strip().lower()
        complaint = str(case.get("chief_complaint") or "").strip().lower()
        symptoms = [str(x).strip().lower() for x in (case.get("symptoms") or []) if str(x).strip()]
        labs = case.get("labs") or {}
        if title and title in text_low:
            score += 3
        if complaint and complaint in text_low:
            score += 3
        for symptom in symptoms:
            if symptom and symptom in text_low:
                score += 2
        for raw_lab in labs.keys():
            key = str(raw_lab).strip().lower()
            mapped = aliases.get(key, key)
            if mapped in matched_analytes or key in matched_analytes:
                score += 1
        if score <= 0:
            continue
        results.append(
            (
                score,
                {
                    "id": case.get("id"),
                    "title": case.get("title"),
                    "likely_diagnoses": case.get("likely_diagnoses") or [],
                    "why": case.get("why") or [],
                    "recommended_tests": case.get("recommended_tests") or [],
                    "red_flags": case.get("red_flags") or [],
                    "followup_questions": case.get("followup_questions") or [],
                },
            )
        )
    results.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in results[:3]]


def _match_analysis_pack(text: str, matched_analytes: set[str]) -> dict[str, Any]:
    text_low = (text or "").strip().lower()
    pack = _load_analysis_pack()
    groups = pack.get("groups") or []
    if not text_low or not isinstance(groups, list):
        return {
            "matched_groups": [],
            "matched_markers": [],
            "suggested_follow_up": [],
            "red_flags": [],
            "candidate_hypotheses": [],
            "sources": pack.get("source_documents") or [],
        }

    matched_groups: list[dict[str, Any]] = []
    matched_markers: list[dict[str, Any]] = []
    follow_up: list[str] = []
    red_flags: list[str] = []
    hypotheses: list[str] = []

    for group in groups:
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("id") or "").strip().lower()
        group_name = str(group.get("name") or "").strip()
        group_markers = group.get("markers") or []
        if not isinstance(group_markers, list):
            continue

        group_hit = False
        local_hits: list[dict[str, Any]] = []
        for marker in group_markers:
            if not isinstance(marker, dict):
                continue
            marker_id = str(marker.get("marker") or "").strip().lower()
            aliases = [str(x).strip().lower() for x in (marker.get("aliases") or []) if str(x).strip()]
            marker_hit = marker_id in matched_analytes
            if not marker_hit:
                for alias in aliases:
                    if len(alias) < 2:
                        continue
                    if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text_low, flags=re.IGNORECASE):
                        marker_hit = True
                        break
            if not marker_hit:
                continue
            group_hit = True
            local_hits.append(
                {
                    "marker": marker_id,
                    "aliases": marker.get("aliases") or [],
                    "patient_safe_summary": marker.get("patient_safe_summary") or "",
                    "doctor_notes": marker.get("doctor_notes") or "",
                    "source": marker.get("source") or "",
                }
            )
            hypotheses.extend([str(x).strip() for x in (marker.get("high_meaning") or []) if str(x).strip()])
            hypotheses.extend([str(x).strip() for x in (marker.get("low_meaning") or []) if str(x).strip()])
            follow_up.extend([str(x).strip() for x in (marker.get("recommended_followup_tests") or []) if str(x).strip()])
            red_flags.extend([str(x).strip() for x in (marker.get("red_flags") or []) if str(x).strip()])

        if group_hit:
            matched_groups.append(
                {
                    "id": group_id,
                    "name": group_name,
                    "sample_type": group.get("sample_type"),
                    "matched_markers": [str(x.get("marker") or "") for x in local_hits if str(x.get("marker") or "").strip()],
                }
            )
            matched_markers.extend(local_hits)

    def _dedup(values: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in values:
            s = str(item or "").strip()
            if not s:
                continue
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
        return out

    return {
        "matched_groups": matched_groups,
        "matched_markers": matched_markers,
        "suggested_follow_up": _dedup(follow_up),
        "red_flags": _dedup(red_flags),
        "candidate_hypotheses": _dedup(hypotheses),
        "sources": pack.get("source_documents") or [],
    }


def _match_master_registry(text: str, matched_analytes: set[str]) -> dict[str, Any]:
    text_low = (text or "").strip().lower()
    payload = _load_master_registry()
    markers = payload.get("markers") or []
    patterns = payload.get("patterns") or []
    if not isinstance(markers, list):
        markers = []
    if not isinstance(patterns, list):
        patterns = []

    matched_markers: list[dict[str, Any]] = []
    marker_ids: set[str] = set()
    follow_up: list[str] = []

    for item in markers:
        if not isinstance(item, dict):
            continue
        marker_id = str(item.get("marker_id") or "").strip().lower()
        if not marker_id:
            continue
        aliases = [str(x).strip().lower() for x in (item.get("aliases") or []) if str(x).strip()]
        hit = marker_id in matched_analytes
        if not hit and text_low:
            for alias in aliases:
                if len(alias) < 2:
                    continue
                if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text_low, flags=re.IGNORECASE):
                    hit = True
                    break
        if not hit:
            continue
        marker_ids.add(marker_id)
        matched_markers.append(
            {
                "marker_id": marker_id,
                "display_name_ru": item.get("display_name_ru") or marker_id,
                "group": item.get("group") or "",
                "patient_safe_summary": item.get("patient_safe_summary") or "",
                "doctor_notes": item.get("doctor_notes") or "",
            }
        )
        follow_up.extend([str(x).strip() for x in (item.get("followup_tests") or []) if str(x).strip()])

    matched_patterns: list[dict[str, Any]] = []
    pattern_hypotheses: list[str] = []
    pattern_red_flags: list[str] = []
    for row in patterns:
        if not isinstance(row, dict):
            continue
        req_all = {str(x).strip().lower() for x in (row.get("trigger_markers_all") or []) if str(x).strip()}
        req_any = {str(x).strip().lower() for x in (row.get("trigger_markers_any") or []) if str(x).strip()}
        if req_all and not req_all.issubset(marker_ids):
            continue
        # If all-required markers are present, any-markers are treated as optional boosters.
        # If all-required set is empty, require at least one marker from any-set.
        if not req_all and req_any and not (req_any & marker_ids):
            continue
        if not req_all and not req_any:
            continue
        matched_patterns.append(
            {
                "pattern_id": row.get("pattern_id"),
                "title_ru": row.get("title_ru"),
                "severity": row.get("severity"),
                "patient_safe_summary": row.get("patient_safe_summary") or "",
                "doctor_notes": row.get("doctor_notes") or "",
            }
        )
        follow_up.extend([str(x).strip() for x in (row.get("followup") or []) if str(x).strip()])
        pattern_hypotheses.extend([str(x).strip() for x in (row.get("candidate_hypotheses") or []) if str(x).strip()])
        if str(row.get("severity") or "").strip().lower() in {"high", "moderate_to_high", "red"}:
            txt = str(row.get("patient_safe_summary") or "").strip()
            if txt:
                pattern_red_flags.append(txt)

    def _dedup(items: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in items:
            s = str(item or "").strip()
            if not s:
                continue
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
        return out

    return {
        "matched_markers": matched_markers[:24],
        "matched_patterns": matched_patterns[:10],
        "candidate_hypotheses": _dedup(pattern_hypotheses)[:12],
        "follow_up_recommendations": _dedup(follow_up)[:20],
        "red_flags": _dedup(pattern_red_flags)[:6],
        "sources": payload.get("source_documents") or [],
    }


def get_lab_panel_preview(profile_name: str) -> dict[str, Any]:
    """Resolve UI profile name to one or more lab panels from medical_knowledge."""
    profile = str(profile_name or "").strip()
    profile_low = profile.lower()
    panels = _load_panels()
    analytes = _load_analytes()
    master_payload = _load_master_registry()
    master_markers = master_payload.get("markers") or []
    master_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(master_markers, list):
        for row in master_markers:
            if not isinstance(row, dict):
                continue
            mk = str(row.get("marker_id") or "").strip().lower()
            if mk and mk not in master_by_id:
                master_by_id[mk] = row

    selected_ids: list[str] = []
    for pid in (_PROFILE_TO_PANEL_IDS.get(profile_low) or []):
        p = str(pid or "").strip().lower()
        if p and p in panels and p not in selected_ids:
            selected_ids.append(p)

    if not selected_ids and profile_low:
        for panel_id, payload in panels.items():
            name_low = str(payload.get("name") or "").strip().lower()
            if profile_low == panel_id or (name_low and profile_low in name_low):
                selected_ids.append(panel_id)

    panel_items: list[dict[str, Any]] = []

    def _clean_str(v: Any) -> str:
        return str(v or "").strip()

    def _first_text(values: list[Any]) -> str:
        for item in values:
            s = _clean_str(item)
            if s:
                return s
        return ""

    def _safe_patient_summary(source: dict[str, Any], marker_name: str) -> str:
        direct = _clean_str(source.get("patient_safe_summary"))
        if direct:
            return direct
        advice = source.get("safe_patient_advice") or []
        if isinstance(advice, list):
            first_advice = _first_text(advice)
            if first_advice:
                return first_advice
        desc = _clean_str(source.get("description_short"))
        if desc:
            return desc
        return f"{marker_name}: оценивать вместе с клинической картиной и референсами лаборатории."

    def _doctor_notes(source: dict[str, Any]) -> str:
        direct = _clean_str(source.get("doctor_notes"))
        if direct:
            return direct
        logic = source.get("interpretation_logic") or []
        limits = source.get("limitations") or []
        interp_limits = ((source.get("interpretation") or {}).get("limitations") or [])
        parts: list[str] = []
        if isinstance(logic, list):
            first_logic = _first_text(logic)
            if first_logic:
                parts.append(first_logic)
        if isinstance(limits, list):
            first_limit = _first_text(limits)
            if first_limit:
                parts.append(first_limit)
        if isinstance(interp_limits, list):
            first_interp_limit = _first_text(interp_limits)
            if first_interp_limit and first_interp_limit not in parts:
                parts.append(first_interp_limit)
        if parts:
            return " ".join(parts[:2])
        return "Клиническая интерпретация требует учета симптомов, анамнеза и референсов лаборатории."

    for panel_id in selected_ids:
        payload = panels.get(panel_id) or {}
        marker_rows: list[dict[str, str]] = []
        for marker in (payload.get("analytes") or []):
            marker_id = str(marker or "").strip().lower()
            if not marker_id:
                continue
            source = analytes.get(marker_id) or {}
            master = master_by_id.get(marker_id) or {}
            marker_name = str(
                source.get("canonical_name")
                or source.get("name")
                or master.get("display_name_ru")
                or marker_id
            )
            marker_rows.append(
                {
                    "id": marker_id,
                    "name": marker_name,
                    "patient_safe_summary": _safe_patient_summary(source or master, marker_name),
                    "doctor_notes": _doctor_notes(source or master),
                }
            )
        panel_items.append(
            {
                "id": panel_id,
                "name": payload.get("name") or panel_id,
                "sample_type": payload.get("sample_type") or "",
                "analytes": marker_rows,
                "recommended_tracking": [str(x).strip() for x in (payload.get("recommended_tracking") or []) if str(x).strip()],
                "updated_at": payload.get("updated_at"),
            }
        )

    return {
        "profile": profile,
        "matched": bool(panel_items),
        "panels": panel_items,
        "panel_count": len(panel_items),
    }


def build_labs_layer_context(
    user_text: str,
    document_text: str,
    complaint_protocol: dict[str, Any] | None = None,
    clinical_profiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    merged_text = ((user_text or "") + "\n" + (document_text or "")).strip()
    matched_ids, matched_aliases = _match_aliases(merged_text)
    matched_set = set(matched_ids)
    analytes = _load_analytes()

    matched_analytes: list[dict[str, Any]] = []
    for analyte_id in matched_ids:
        payload = analytes.get(analyte_id) or {}
        matched_analytes.append(
            {
                "id": analyte_id,
                "name": payload.get("name"),
                "panel_ids": payload.get("panel_ids") or [],
                "aliases_matched": sorted(set(matched_aliases.get(analyte_id) or [])),
                "reference_ranges": payload.get("reference_ranges") or [],
                "red_flags": payload.get("red_flags") or [],
            }
        )

    matched_panels = _select_panels(matched_set)
    matched_patterns = _pick_pattern_rules(matched_set)
    matched_red_flags = _pick_red_flags(matched_set, merged_text)
    follow_up = _pick_follow_up(matched_set, matched_patterns)
    analysis_pack = _match_analysis_pack(merged_text, matched_set)
    master_ctx = _match_master_registry(merged_text, matched_set)

    complaint_name = str((complaint_protocol or {}).get("complaint") or "")
    complaint_links = _match_complaint_links(complaint_name)
    disease_names = [str((item or {}).get("name") or "") for item in (clinical_profiles or [])]
    disease_links = _match_disease_links(disease_names)
    symptom_matches = _match_symptoms(merged_text)
    matched_cases = _match_cases(merged_text, matched_set)
    symptom_tests: list[str] = []
    symptom_hypotheses: list[str] = []
    symptom_followup: list[str] = []
    for item in symptom_matches:
        symptom_tests.extend([str(x).strip() for x in (item.get("recommended_tests") or []) if str(x).strip()])
        symptom_hypotheses.extend([str(x).strip() for x in (item.get("possible_diseases") or []) if str(x).strip()])
        symptom_followup.extend([str(x).strip() for x in (item.get("followup_questions") or []) if str(x).strip()])
    for test in symptom_tests:
        if test.lower() not in {x.lower() for x in follow_up}:
            follow_up.append(test)
    for test in (analysis_pack.get("suggested_follow_up") or []):
        if str(test).strip() and str(test).lower() not in {x.lower() for x in follow_up}:
            follow_up.append(str(test).strip())
    for test in (master_ctx.get("follow_up_recommendations") or []):
        if str(test).strip() and str(test).lower() not in {x.lower() for x in follow_up}:
            follow_up.append(str(test).strip())
    symptom_hypotheses.extend([str(x).strip() for x in (analysis_pack.get("candidate_hypotheses") or []) if str(x).strip()])
    symptom_hypotheses.extend([str(x).strip() for x in (master_ctx.get("candidate_hypotheses") or []) if str(x).strip()])

    pipeline = _load_diagnostic_pipeline()
    core = _load_medical_core()
    output_template = _load_output_template()
    prompt_addon = _load_system_prompt_addon()
    reasoning_engine_prompt = _load_reasoning_engine_prompt()
    retrieval_ranking_prompt = _load_retrieval_ranking_prompt()
    lab_result_parser_prompt = _load_lab_result_parser_prompt()
    clinical_guardrail_prompt = _load_clinical_guardrail_prompt()
    evidence_weighting_prompt = _load_evidence_weighting_prompt()
    adaptive_question_prompt = _load_adaptive_question_prompt()

    return {
        "source_priority": [
            "clinical_guidelines",
            "ontologies",
            "disease_clinical_profiles",
            "labs_educational_sources",
            "wellness_or_low_confidence",
        ],
        "matched_analytes": matched_analytes,
        "matched_panels": matched_panels,
        "matched_patterns": matched_patterns,
        "matched_red_flags": matched_red_flags,
        "follow_up_recommendations": follow_up,
        "symptom_matches": symptom_matches,
        "symptom_hypotheses": list(dict.fromkeys(symptom_hypotheses)),
        "symptom_followup_questions": list(dict.fromkeys(symptom_followup)),
        "analysis_interpretation_pack": analysis_pack,
        "master_marker_context": master_ctx,
        "matched_training_cases": matched_cases,
        "complaint_lab_links": complaint_links,
        "disease_lab_links": disease_links,
        "assistant_contract": pipeline,
        "medical_core": core,
        "output_template": output_template,
        "assistant_prompt_addon": prompt_addon,
        "reasoning_engine_prompt": reasoning_engine_prompt,
        "retrieval_ranking_prompt": retrieval_ranking_prompt,
        "lab_result_parser_prompt": lab_result_parser_prompt,
        "adaptive_question_prompt": adaptive_question_prompt,
        "evidence_weighting_prompt": evidence_weighting_prompt,
        "clinical_guardrail_prompt": clinical_guardrail_prompt,
    }
