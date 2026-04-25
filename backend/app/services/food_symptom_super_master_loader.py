from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MASTER_FILE = _PROJECT_ROOT / "app" / "knowledge" / "food_symptom_super_master.json"
_TEMPLATES_FILE = _PROJECT_ROOT / "app" / "knowledge" / "patient_safe_templates.json"
_ROUTING_FILE = _PROJECT_ROOT / "app" / "knowledge" / "routing_rules.json"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\wа-яёА-ЯЁ ]+", " ", str(text or "").lower())).strip()


def _load_json(path: Path, fallback: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return fallback


@lru_cache(maxsize=1)
def load_food_symptom_super_master() -> dict[str, Any]:
    payload = _load_json(_MASTER_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def load_patient_safe_templates() -> dict[str, Any]:
    payload = _load_json(_TEMPLATES_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def load_routing_rules() -> dict[str, Any]:
    payload = _load_json(_ROUTING_FILE, {})
    return payload if isinstance(payload, dict) else {}


def _cause_titles() -> dict[str, str]:
    rows = load_food_symptom_super_master().get("causes")
    out: dict[str, str] = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            cid = str(row.get("id") or "").strip()
            title = str(row.get("title") or "").strip()
            if cid and title:
                out[cid] = title
    return out


def _symptom_aliases() -> dict[str, list[str]]:
    rr = load_routing_rules()
    norm = rr.get("normalization") if isinstance(rr.get("normalization"), dict) else {}
    aliases = norm.get("symptom_synonyms") if isinstance(norm.get("symptom_synonyms"), dict) else {}
    out: dict[str, list[str]] = {}
    for key, rows in aliases.items():
        if isinstance(rows, list):
            out[str(key)] = [str(x).strip().lower() for x in rows if str(x).strip()]
    return out


def detect_trigger_groups(message: str) -> list[str]:
    t = _norm(message)
    rr = load_routing_rules()
    norm = rr.get("normalization") if isinstance(rr.get("normalization"), dict) else {}
    trigger_syn = norm.get("trigger_synonyms") if isinstance(norm.get("trigger_synonyms"), dict) else {}
    groups: list[str] = []
    for group_name, synonyms in trigger_syn.items():
        if isinstance(synonyms, list) and any(_norm(str(s)) in t for s in synonyms):
            groups.append(str(group_name))
    # Fallback markers
    if "fatty_fried" not in groups and any(x in t for x in ("жирн", "жарен", "семеч", "орех", "фастфуд")):
        groups.append("fatty_fried")
    if "dairy" not in groups and any(x in t for x in ("молок", "творог", "сливк", "йогурт", "кефир")):
        groups.append("dairy")
    if "sweet_load" not in groups and any(x in t for x in ("сладк", "десерт", "шоколад", "сахар")):
        groups.append("sweet_load")
    return groups


def detect_red_flags(message: str) -> list[str]:
    t = _norm(message)
    rr = load_routing_rules()
    rf = rr.get("red_flag_rules") if isinstance(rr.get("red_flag_rules"), dict) else {}
    match_any = rf.get("match_any") if isinstance(rf.get("match_any"), list) else []
    out = [str(x).strip() for x in match_any if _norm(str(x)) in t]
    # Additional robust checks
    if "обморок" not in out and "обмор" in t:
        out.append("обморок")
    if "чёрный стул" not in out and ("черн" in t or "чёрн" in t) and "стул" in t:
        out.append("чёрный стул")
    return out[:8]


def detect_zone(message: str) -> str:
    t = _norm(message)
    rr = load_routing_rules()
    zone_rules = rr.get("zone_rules") if isinstance(rr.get("zone_rules"), list) else []
    aliases = _symptom_aliases()
    for row in zone_rules:
        if not isinstance(row, dict):
            continue
        zone = str(row.get("zone") or "").strip()
        symptoms = row.get("if_any_symptoms") if isinstance(row.get("if_any_symptoms"), list) else []
        expanded: list[str] = []
        for s in symptoms:
            key = str(s).strip().lower()
            expanded.append(key)
            expanded.extend(aliases.get(key, []))
        if any(_norm(x) in t for x in expanded if x):
            return zone
    return "upper_gi_zone"


def detect_cluster(message: str, zone: str, trigger_groups: list[str], recurrent: bool = False) -> str:
    t = _norm(message)
    rr = load_routing_rules()
    rows = rr.get("cluster_rules") if isinstance(rr.get("cluster_rules"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        req_zone = str(row.get("requires_zone") or "").strip()
        if req_zone and req_zone != zone:
            continue
        req_trigger = str(row.get("requires_trigger_group") or "").strip()
        if req_trigger and req_trigger not in trigger_groups:
            continue
        req_symptoms = row.get("requires_any_symptoms") if isinstance(row.get("requires_any_symptoms"), list) else []
        if req_symptoms and not any(_norm(str(s)) in t for s in req_symptoms):
            continue
        ctx_flags = row.get("requires_context_flags") if isinstance(row.get("requires_context_flags"), list) else []
        if "recurrent_pattern" in ctx_flags and not recurrent:
            continue
        cluster = str(row.get("cluster") or "").strip()
        if cluster:
            return cluster
    # Fallback by zone
    if zone == "right_upper_abdominal_zone":
        return "right_upper_abdominal_discomfort_after_fatty_food"
    if zone == "bowel_zone":
        return "bloating_gas_after_onion_garlic_beans_fruit_juice_honey"
    if zone == "systemic_zone":
        return "sleepiness_weakness_after_heavy_meal"
    return "upper_abdominal_heaviness_after_food"


def rank_causes(message: str, cluster: str, trigger_groups: list[str], recurrent: bool = False, limit: int = 4) -> list[dict[str, str]]:
    titles = _cause_titles()
    sm = load_food_symptom_super_master()
    sc = sm.get("symptom_clusters") if isinstance(sm.get("symptom_clusters"), dict) else {}
    cluster_row = sc.get(cluster) if isinstance(sc.get(cluster), dict) else {}
    ids = cluster_row.get("ranked_causes") if isinstance(cluster_row.get("ranked_causes"), list) else []
    if not ids:
        z = detect_zone(message)
        zones = sm.get("zones") if isinstance(sm.get("zones"), dict) else {}
        zr = zones.get(z) if isinstance(zones.get(z), dict) else {}
        ids = zr.get("top_patterns") if isinstance(zr.get("top_patterns"), list) else []
    t = _norm(message)
    ids = [str(x).strip() for x in ids if str(x).strip()]
    if "sweet_load" in trigger_groups and "sugar_glucose_pattern" in ids:
        ids.remove("sugar_glucose_pattern")
        ids.insert(0, "sugar_glucose_pattern")
    if "histamine_like" in trigger_groups:
        has_hist_sym = any(x in t for x in ("покрасн", "сердц", "залож", "зуд"))
        if has_hist_sym:
            ids.append("histamine_conditional_pattern")
    if "ibs_pattern_if_recurrent" in ids and (not recurrent) and not any(x in t for x in ("повтор", "дефекац", "изменение стула", "хронич")):
        ids = [x for x in ids if x != "ibs_pattern_if_recurrent"]
    if "pancreatic_warning_if_severe" in ids and not any(x in t for x in ("сильн", "нараста", "в спину", "рвот", "температур")):
        ids = [x for x in ids if x != "pancreatic_warning_if_severe"]

    rr = load_routing_rules()
    overrides = rr.get("cause_ranking_overrides") if isinstance(rr.get("cause_ranking_overrides"), list) else []
    for row in overrides:
        if not isinstance(row, dict):
            continue
        trg = str(row.get("if_trigger_group") or "").strip()
        if trg and trg not in trigger_groups:
            continue
        cond_sym = row.get("if_any_symptoms") if isinstance(row.get("if_any_symptoms"), list) else []
        if cond_sym and not any(_norm(str(s)) in t for s in cond_sym):
            continue
        promote = row.get("promote") if isinstance(row.get("promote"), list) else []
        for cid in reversed([str(x).strip() for x in promote if str(x).strip()]):
            if cid in ids:
                ids.remove(cid)
            ids.insert(0, cid)

    out: list[dict[str, str]] = []
    for cid in ids[: max(1, int(limit or 1))]:
        out.append({"id": cid, "title": titles.get(cid, cid)})
    return out


def select_template(cluster: str) -> str:
    rr = load_routing_rules()
    rows = rr.get("template_selection_rules") if isinstance(rr.get("template_selection_rules"), list) else []
    for row in rows:
        if isinstance(row, dict) and str(row.get("if_cluster") or "").strip() == cluster:
            tpl = str(row.get("template") or "").strip()
            if tpl:
                return tpl
    return "base_response"


def classify_super(message: str, recurrent: bool = False) -> dict[str, Any]:
    zone = detect_zone(message)
    trigger_groups = detect_trigger_groups(message)
    cluster = detect_cluster(message, zone, trigger_groups, recurrent=recurrent)
    red = detect_red_flags(message)
    ranked = rank_causes(message, cluster=cluster, trigger_groups=trigger_groups, recurrent=recurrent, limit=4)
    return {
        "zone": zone,
        "cluster": cluster,
        "trigger_groups": trigger_groups,
        "red_flags": red,
        "ranked_causes": ranked,
        "template": select_template(cluster),
    }


def single_mild_message() -> str:
    tl = load_food_symptom_super_master().get("tests_logic")
    if not isinstance(tl, dict):
        return "При единичном лёгком эпизоде без красных флагов срочные анализы обычно не нужны."
    row = tl.get("single_mild_episode")
    if not isinstance(row, dict):
        return "При единичном лёгком эпизоде без красных флагов срочные анализы обычно не нужны."
    return str(row.get("message") or "").strip() or "При единичном лёгком эпизоде без красных флагов срочные анализы обычно не нужны."


def recurrent_fatty_ruq_tests() -> list[str]:
    tl = load_food_symptom_super_master().get("tests_logic")
    if not isinstance(tl, dict):
        return []
    row = tl.get("recurrent_upper_gi_or_fatty_food_pattern")
    tests = row.get("recommend_tests") if isinstance(row, dict) else []
    return [str(x).strip() for x in (tests or []) if str(x).strip()]


def build_patient_safe_response(template_id: str, ranked_causes: list[dict[str, str]], recurrent: bool = False) -> str:
    templates = load_patient_safe_templates()
    tpl_root = templates.get("templates") if isinstance(templates.get("templates"), dict) else {}
    tpl = tpl_root.get(template_id) if isinstance(tpl_root.get(template_id), dict) else {}
    if not tpl:
        tpl = tpl_root.get("base_response") if isinstance(tpl_root.get("base_response"), dict) else {}

    likely = str((ranked_causes[0] or {}).get("title") or "").strip() if ranked_causes else ""
    alt_titles = [str(x.get("title") or "").strip() for x in ranked_causes[1:3] if str(x.get("title") or "").strip()]

    most_likely = str(tpl.get("most_likely") or "").strip()
    alternatives = tpl.get("alternatives") if isinstance(tpl.get("alternatives"), list) else []
    what_to_do = tpl.get("what_to_do_now") if isinstance(tpl.get("what_to_do_now"), list) else []
    urgent = tpl.get("urgent_signs") if isinstance(tpl.get("urgent_signs"), list) else []
    tests = tpl.get("tests_if_recurrent") if isinstance(tpl.get("tests_if_recurrent"), list) else []

    parts: list[str] = []
    parts.append("Что вероятнее всего:")
    if most_likely:
        parts.append(most_likely)
    elif likely:
        parts.append(likely)
    parts.append("Какие ещё причины возможны:")
    alt_lines = [str(x).strip() for x in alternatives if str(x).strip()]
    if not alt_lines:
        alt_lines = alt_titles
    parts.extend(f"- {x}" for x in alt_lines[:3])
    parts.append("Что делать сейчас:")
    parts.extend(f"- {str(x).strip()}" for x in what_to_do if str(x).strip())
    parts.append("Когда срочно обращаться:")
    parts.extend(f"- {str(x).strip()}" for x in urgent if str(x).strip())
    if recurrent:
        parts.append("Нужны ли анализы, если это повторяется:")
        parts.extend(f"- {str(x).strip()}" for x in tests if str(x).strip())
    else:
        parts.append("Нужны ли анализы, если это повторяется:")
        parts.append(f"- {single_mild_message()}")
    return "\n".join(parts)

