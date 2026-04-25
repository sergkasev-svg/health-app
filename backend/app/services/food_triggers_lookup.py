from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_FOOD_ROOT = _PROJECT_ROOT / "medical_knowledge" / "food_triggers"
_FOODS_DIR = _FOOD_ROOT / "foods"
_COMPOUNDS_DIR = _FOOD_ROOT / "compounds"
_SYMPTOM_LINKS_DIR = _FOOD_ROOT / "symptom_links"
_RULES_DIR = _FOOD_ROOT / "rules"
_CONCIERGE_PROMPT_FILE = _FOOD_ROOT / "templates" / "food_trigger_concierge_prompt.txt"
_REPORT_PROMPT_FILE = _FOOD_ROOT / "templates" / "food_trigger_report_prompt.txt"
_GUT_ROOT = _PROJECT_ROOT / "medical_knowledge" / "gut_triggers"
_GUT_RULES_FILE = _GUT_ROOT / "rules" / "gut_trigger_patterns.json"
_GUT_CONCIERGE_PROMPT_FILE = _GUT_ROOT / "templates" / "gut_trigger_concierge_prompt.txt"
_HIST_COMPLAINTS_FILE = _PROJECT_ROOT / "medical_knowledge" / "complaints" / "histamine_food_related_complaints.json"
_HIST_RULES_FILE = _PROJECT_ROOT / "medical_knowledge" / "diagnostic_rules" / "food_histamine_rules.json"
_HIST_CORE_FILE = _PROJECT_ROOT / "medical_knowledge" / "histamine" / "histamine_core.json"
_MCAS_CORE_FILE = _PROJECT_ROOT / "medical_knowledge" / "mast_cells" / "mast_cell_core.json"
_NUTRITION_HIST_FILE = _PROJECT_ROOT / "medical_knowledge" / "nutrition" / "food_compatibility_and_histamine.json"
_AMINES_FILE = _PROJECT_ROOT / "medical_knowledge" / "food_triggers" / "biogenic_amines_and_phenols.json"
_BACKGROUND_FILE = _PROJECT_ROOT / "medical_knowledge" / "pathophysiology" / "background_factors.json"
_HIST_RAG_FILE = _PROJECT_ROOT / "medical_knowledge" / "rag" / "food_histamine_chunks.jsonl"
_HIST_PDF_PROMPT_FILE = _PROJECT_ROOT / "medical_knowledge" / "histamine" / "pdf_prompt_library.json"
_MCAS_COMORBID_FILE = _PROJECT_ROOT / "medical_knowledge" / "histamine" / "mcas_comorbid_module.json"
_SYMPTOM_INTELLIGENCE_FILE = _PROJECT_ROOT / "medical_knowledge" / "histamine" / "symptom_intelligence_module.json"
_CAUSAL_ENGINE_FILE = _PROJECT_ROOT / "medical_knowledge" / "histamine" / "causal_engine_module.json"
_NON_DRUG_ENGINE_FILE = _PROJECT_ROOT / "medical_knowledge" / "histamine" / "non_drug_engine_module.json"
_NUTRACEUTICAL_ENGINE_FILE = _PROJECT_ROOT / "medical_knowledge" / "histamine" / "nutraceutical_engine_module.json"
_AMINO_ENGINE_FILE = _PROJECT_ROOT / "medical_knowledge" / "histamine" / "amino_acid_engine_module.json"


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
def _load_foods() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not _FOODS_DIR.exists():
        return out
    for fp in sorted(_FOODS_DIR.glob("*.json")):
        item = _load_json(fp, {})
        if not isinstance(item, dict):
            continue
        food_id = str(item.get("id") or fp.stem).strip().lower()
        if food_id:
            out[food_id] = item
    return out


@lru_cache(maxsize=1)
def _load_compounds() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not _COMPOUNDS_DIR.exists():
        return out
    for fp in sorted(_COMPOUNDS_DIR.glob("*.json")):
        item = _load_json(fp, {})
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or fp.stem).strip().lower()
        if cid:
            out[cid] = item
    return out


@lru_cache(maxsize=1)
def _load_symptom_links() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not _SYMPTOM_LINKS_DIR.exists():
        return out
    for fp in sorted(_SYMPTOM_LINKS_DIR.glob("*.json")):
        item = _load_json(fp, {})
        if isinstance(item, dict) and item:
            out.append(item)
    return out


@lru_cache(maxsize=1)
def _load_trigger_patterns() -> list[dict[str, Any]]:
    payload = _load_json(_RULES_DIR / "trigger_patterns.json", [])
    return payload if isinstance(payload, list) else []


@lru_cache(maxsize=1)
def _load_gut_trigger_patterns() -> list[dict[str, Any]]:
    payload = _load_json(_GUT_RULES_FILE, [])
    return payload if isinstance(payload, list) else []


@lru_cache(maxsize=1)
def _load_histamine_complaints() -> list[dict[str, Any]]:
    payload = _load_json(_HIST_COMPLAINTS_FILE, [])
    return payload if isinstance(payload, list) else []


@lru_cache(maxsize=1)
def _load_histamine_rules() -> list[dict[str, Any]]:
    payload = _load_json(_HIST_RULES_FILE, [])
    return payload if isinstance(payload, list) else []


@lru_cache(maxsize=1)
def _load_histamine_core() -> dict[str, Any]:
    payload = _load_json(_HIST_CORE_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _load_mcas_core() -> dict[str, Any]:
    payload = _load_json(_MCAS_CORE_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _load_nutrition_histamine() -> dict[str, Any]:
    payload = _load_json(_NUTRITION_HIST_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _load_biogenic_amines() -> dict[str, Any]:
    payload = _load_json(_AMINES_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _load_background_factors() -> dict[str, Any]:
    payload = _load_json(_BACKGROUND_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _load_histamine_rag_chunks() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        if not _HIST_RAG_FILE.exists():
            return out
        for raw in _HIST_RAG_FILE.read_text(encoding="utf-8").splitlines():
            line = str(raw or "").strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                out.append(row)
    except Exception:
        return []
    return out


@lru_cache(maxsize=1)
def _load_histamine_pdf_prompt_library() -> dict[str, Any]:
    payload = _load_json(_HIST_PDF_PROMPT_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _load_mcas_comorbid_module() -> dict[str, Any]:
    payload = _load_json(_MCAS_COMORBID_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _load_symptom_intelligence_module() -> dict[str, Any]:
    payload = _load_json(_SYMPTOM_INTELLIGENCE_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _load_causal_engine_module() -> dict[str, Any]:
    payload = _load_json(_CAUSAL_ENGINE_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _load_non_drug_engine_module() -> dict[str, Any]:
    payload = _load_json(_NON_DRUG_ENGINE_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _load_nutraceutical_engine_module() -> dict[str, Any]:
    payload = _load_json(_NUTRACEUTICAL_ENGINE_FILE, {})
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _load_amino_engine_module() -> dict[str, Any]:
    payload = _load_json(_AMINO_ENGINE_FILE, {})
    return payload if isinstance(payload, dict) else {}


def _match_alias(text_low: str, alias: str) -> bool:
    a = str(alias or "").strip().lower()
    if len(a) < 2:
        return False
    if re.search(r"[а-яё]", a, flags=re.IGNORECASE):
        return a in text_low
    return bool(re.search(rf"(?<!\w){re.escape(a)}(?!\w)", text_low, flags=re.IGNORECASE))


def _match_food_ids(text: str) -> set[str]:
    t = (text or "").lower()
    if not t:
        return set()
    out: set[str] = set()
    for food_id, item in _load_foods().items():
        aliases = [food_id] + [str(x).strip().lower() for x in (item.get("aliases") or []) if str(x).strip()]
        for alias in aliases:
            if len(alias) < 3:
                continue
            if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", t, flags=re.IGNORECASE):
                out.add(food_id)
                break
            # RU morphology fallback: catch simple inflections like "сыр" -> "сыра".
            if re.search(r"[а-яё]", alias, flags=re.IGNORECASE) and alias in t:
                out.add(food_id)
                break
    return out


def _detect_symptoms(text: str) -> set[str]:
    t = (text or "").lower()
    symptoms: set[str] = set()
    if any(k in t for k in ("голов", "мигр", "цефал")):
        symptoms.update({"headache", "migraine"})
    if any(k in t for k in ("сып", "зуд", "чеш", "покрасн", "красне", "аллерг", "прилив")):
        symptoms.add("allergy")
    if any(k in t for k in ("живот", "жкт", "диаре", "понос", "тошнот", "рвот", "изжог", "вздут", "газ", "пуч", "урчит")):
        symptoms.add("gi")
    return symptoms


def _contains_ru_phrase(text_low: str, phrase: str) -> bool:
    p = str(phrase or "").strip().lower()
    if len(p) < 3:
        return False
    if re.search(r"[а-яё]", p, flags=re.IGNORECASE):
        return p in text_low
    return bool(re.search(rf"(?<!\w){re.escape(p)}(?!\w)", text_low, flags=re.IGNORECASE))


def _dedup_texts(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in items:
        s = str(x or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _extract_histamine_layer(
    merged_low: str,
    symptoms: set[str],
) -> dict[str, Any]:
    matched_complaints: list[dict[str, Any]] = []
    matched_rules: list[dict[str, Any]] = []
    possible_conditions: list[str] = []
    followup_questions: list[str] = []
    safe_recommendations: list[str] = []
    matched_compounds: set[str] = set()
    rag_hits: list[str] = []

    for c in _load_histamine_complaints():
        phrases = [str(x).strip() for x in (c.get("user_phrases") or []) if str(x).strip()]
        if not phrases:
            continue
        if not any(_contains_ru_phrase(merged_low, p) for p in phrases):
            continue
        matched_complaints.append(
            {
                "id": str(c.get("id") or "").strip(),
                "name": str(c.get("name") or "").strip(),
                "user_phrases": phrases[:4],
            }
        )
        possible_conditions.extend([str(x).strip() for x in (c.get("possible_causes") or []) if str(x).strip()])
        followup_questions.extend([str(x).strip() for x in (c.get("must_ask") or []) if str(x).strip()])
        safe_recommendations.extend([str(x).strip() for x in (c.get("safe_actions") or []) if str(x).strip()])

    for r in _load_histamine_rules():
        complaint_phrase = str(r.get("complaint") or "").strip()
        if not complaint_phrase:
            continue
        if not _contains_ru_phrase(merged_low, complaint_phrase):
            continue
        matched_rules.append(
            {
                "rule_id": str(r.get("rule_id") or "").strip(),
                "complaint": complaint_phrase,
            }
        )
        possible_conditions.extend([str(x).strip() for x in (r.get("top_causes") or []) if str(x).strip()])
        followup_questions.extend([str(x).strip() for x in (r.get("ask") or []) if str(x).strip()])
        safe_recommendations.extend([str(x).strip() for x in (r.get("do") or []) if str(x).strip()])

    amines = _load_biogenic_amines()
    for compound_id, payload in amines.items():
        if not isinstance(payload, dict):
            continue
        foods = [str(x).strip() for x in ((payload.get("foods") or payload.get("sources") or [])) if str(x).strip()]
        matched = any(_contains_ru_phrase(merged_low, f) for f in foods)
        if not matched and not any(_contains_ru_phrase(merged_low, s) for s in (payload.get("symptoms") or [])):
            continue
        cid = str(compound_id or "").strip().lower()
        if cid:
            matched_compounds.add(cid)
            possible_conditions.append("чувствительность к " + cid.replace("_", " "))

    hcore = _load_histamine_core()
    mcas = _load_mcas_core()
    nutrition = _load_nutrition_histamine()
    background = _load_background_factors()

    core_triggers = [str(x).strip() for x in (hcore.get("common_triggers") or []) if str(x).strip()]
    core_symptoms = [str(x).strip() for x in (hcore.get("symptoms") or []) if str(x).strip()]
    complaint_patterns = [str(x).strip() for x in (hcore.get("complaint_patterns") or []) if str(x).strip()]
    low_histamine_notes = [str(x).strip() for x in (nutrition.get("low_histamine_notes") or []) if str(x).strip()]
    mcas_notes = [str(x).strip() for x in (mcas.get("notes") or []) if str(x).strip()]
    background_factors = [str(x).strip() for x in (background.get("background_factors") or []) if str(x).strip()]

    has_histamine_signal = bool(
        matched_complaints
        or matched_rules
        or any(_contains_ru_phrase(merged_low, p) for p in complaint_patterns)
        or any(_contains_ru_phrase(merged_low, t) for t in core_triggers)
        or any(_contains_ru_phrase(merged_low, s) for s in core_symptoms)
        or ("allergy" in symptoms and any(_contains_ru_phrase(merged_low, x) for x in ("вино", "сыр", "фермент")))
    )

    if has_histamine_signal:
        possible_conditions.extend(
            [
                "чувствительность к гистамину",
                "чувствительность к биогенным аминам",
            ]
        )
        safe_recommendations.extend(low_histamine_notes[:2])
        if mcas_notes:
            possible_conditions.append("MCAS-подобная гиперреактивность (требует очной оценки)")
        followup_questions.extend(
            [
                "Есть ли покраснение, зуд, заложенность носа или тахикардия вместе с симптомом?",
                "Повторяется ли реакция на вино, выдержанные сыры или ферментированные продукты?",
            ]
        )

    query_tags: set[str] = set()
    if any(k in merged_low for k in ("сыр", "вино", "мигр", "голов")):
        query_tags.update({"food_trigger", "headache", "histamine", "tyramine"})
    if any(k in merged_low for k in ("кефир", "молок", "газы", "вздут", "фасол", "бобов", "пуч")):
        query_tags.update({"gas", "bloating", "milk", "lactose", "beans", "fermentation"})

    for row in _load_histamine_rag_chunks():
        text = str(row.get("text") or "").strip()
        tags = [str(x).strip().lower() for x in (row.get("tags") or []) if str(x).strip()]
        if not text:
            continue
        if set(tags) & query_tags:
            rag_hits.append(text)
    rag_hits = _dedup_texts(rag_hits)[:3]

    return {
        "matched_complaints": matched_complaints,
        "matched_rules": matched_rules,
        "matched_compound_ids": sorted(matched_compounds),
        "possible_conditions": _dedup_texts(possible_conditions),
        "followup_questions": _dedup_texts(followup_questions),
        "safe_recommendations": _dedup_texts(safe_recommendations),
        "rag_hits": rag_hits,
        "priority_note": "clinical_guidelines > ontologies > disease_clinical_profiles > food_trigger_rules(histamine_layer)",
        "education_notes": _dedup_texts(mcas_notes[:1] + background_factors[:2]),
    }


def _extract_pdf_prompt_layer(merged_low: str) -> dict[str, Any]:
    lib = _load_histamine_pdf_prompt_library()
    docs = lib.get("documents") or []
    if not isinstance(docs, list):
        docs = []

    matched_docs: list[dict[str, Any]] = []
    possible_conditions: list[str] = []
    followups: list[str] = []
    recommended_tests: list[str] = []
    for row in docs:
        if not isinstance(row, dict):
            continue
        tags = [str(x).strip().lower() for x in (row.get("priority_tags") or []) if str(x).strip()]
        name = str(row.get("source_path") or "").strip().lower()
        text_signals = list(tags)
        for tag in list(tags):
            for part in re.split(r"[_\-/\s]+", tag):
                ps = str(part).strip().lower()
                if ps:
                    text_signals.append(ps)
        if name:
            text_signals.extend(name.replace("/", " ").replace("\\", " ").split())
        text_signals = [x for x in text_signals if len(x) >= 4]
        if not text_signals:
            continue
        if not any(sig in merged_low for sig in text_signals):
            continue
        matched_docs.append(
            {
                "doc_id": str(row.get("doc_id") or "").strip(),
                "status": str(row.get("status") or "").strip(),
                "source_path": str(row.get("source_path") or "").strip(),
            }
        )
        possible_conditions.extend([str(x).strip() for x in (row.get("diagnostic_hypotheses") or []) if str(x).strip()])
        followups.extend([str(x).strip() for x in (row.get("followup_questions") or []) if str(x).strip()])
        recommended_tests.extend([str(x).strip() for x in (row.get("recommended_tests") or []) if str(x).strip()])

    links = lib.get("cross_document_links") or {}
    if isinstance(links, dict):
        panel = str(links.get("lab_profile_target") or "").strip()
        route = str(links.get("doctor_route_target") or "").strip()
        if panel:
            recommended_tests.append("panel:" + panel)
        if route:
            followups.append("Планово обратиться к профильному специалисту: " + route + ".")

    return {
        "matched_docs": matched_docs,
        "possible_conditions": _dedup_texts(possible_conditions),
        "followup_questions": _dedup_texts(followups),
        "recommended_tests": _dedup_texts(recommended_tests),
    }


def _has_mcas_overlap_signals(merged_low: str) -> bool:
    keys = (
        "гистамин",
        "mcas",
        "сатк",
        "тучн",
        "дисплаз",
        "дст",
        "pots",
        "ортостат",
        "тахикард",
        "постковид",
        "long covid",
        "хроническ",
        "утомляем",
        "срк",
        "мигрен",
        "фибромиал",
        "тревог",
        "цистит",
        "вульводин",
        "сдвг",
        "внчс",
        "беспокойных ног",
        "метеочувств",
    )
    return any(k in merged_low for k in keys)


def _has_symptom_intelligence_signals(merged_low: str) -> bool:
    keys = (
        "мультисистем",
        "мигрир",
        "зуд",
        "крапив",
        "дермограф",
        "песок в глазах",
        "жжение глаз",
        "заложенность носа",
        "непереносимость запахов",
        "ком в горле",
        "ангиоотек",
        "изжога",
        "диар",
        "запор",
        "гастропарез",
        "после дефекации",
        "после туалета",
        "тахикард",
        "гипотенз",
        "туман в голове",
        "паник",
        "тревог",
        "отеки",
        "одышка",
        "хрипы",
    )
    return any(k in merged_low for k in keys)


def _has_causal_engine_signals(merged_low: str) -> bool:
    keys = (
        "с детства",
        "подростков",
        "после стресса",
        "после инфекции",
        "после переезда",
        "после путешествия",
        "гормон",
        "антибиотик",
        "дисбиоз",
        "метилирован",
        "сульфат",
        "детокс",
        "печень",
        "желчеотток",
        "фенол",
        "запах",
        "косметик",
        "бытовая химия",
        "при вставании",
    )
    return any(k in merged_low for k in keys)


def _has_non_drug_engine_signals(merged_low: str) -> bool:
    keys = (
        "без лекарств",
        "без нутрицевтик",
        "рацион",
        "свежая пища",
        "голодан",
        "низкогистамин",
        "без сахара",
        "добавки e",
        "вздут",
        "тошнот",
        "тяжесть после еды",
        "детокс",
        "желчеотток",
        "лимфодренаж",
        "электролит",
        "постпрандиаль",
        "пост",
        "ортостат",
    )
    return any(k in merged_low for k in keys)


def _has_nutraceutical_engine_signals(merged_low: str) -> bool:
    keys = (
        "нутрицевтик",
        "добавк",
        "бад",
        "кверцетин",
        "лютеолин",
        "бромелайн",
        "витамин c",
        "кетотифен",
        "омализумаб",
        "пропранолол",
        "ивабрадин",
        "start low",
        "парадоксальн",
        "дробн",
    )
    return any(k in merged_low for k in keys)


def _has_amino_engine_signals(merged_low: str) -> bool:
    keys = (
        "аминокислот",
        "глутатион",
        "глутамин",
        "глутамат",
        "триптофан",
        "карнитин",
        "аргинин",
        "глицин",
        "пролин",
        "метилирован",
        "сульфатац",
        "митохонд",
        "нейромедиатор",
        "детокс",
    )
    return any(k in merged_low for k in keys)


def _extract_mcas_comorbid_layer(merged_low: str) -> dict[str, Any]:
    payload = _load_mcas_comorbid_module()
    conditions = payload.get("conditions") or []
    clusters = payload.get("symptom_clusters") or []
    mediators = payload.get("mediators") or []
    patterns = payload.get("patterns") or []
    if not isinstance(conditions, list):
        conditions = []
    if not isinstance(clusters, list):
        clusters = []
    if not isinstance(mediators, list):
        mediators = []
    if not isinstance(patterns, list):
        patterns = []

    def _signals(row: dict[str, Any]) -> list[str]:
        raw: list[str] = []
        raw.extend([str(x).strip().lower() for x in (row.get("linked_symptoms") or []) if str(x).strip()])
        raw.extend([str(x).strip().lower() for x in (row.get("triggers") or []) if str(x).strip()])
        raw.extend([str(x).strip().lower() for x in (row.get("linked_conditions") or []) if str(x).strip()])
        raw.extend([str(x).strip().lower() for x in (row.get("related_markers") or []) if str(x).strip()])
        raw.extend(
            [
                str(row.get("id") or "").strip().lower(),
                str(row.get("display_name_ru") or "").strip().lower(),
                str(row.get("summary") or "").strip().lower(),
            ]
        )
        out: list[str] = []
        for src in raw:
            if not src:
                continue
            out.append(src)
            for part in re.split(r"[_\-/\s,()]+", src):
                p = str(part or "").strip().lower()
                if len(p) >= 4:
                    out.append(p)
        return [x for x in out if len(x) >= 4]

    matched_conditions: list[dict[str, Any]] = []
    matched_clusters: list[dict[str, Any]] = []
    matched_mediators: list[dict[str, Any]] = []
    matched_patterns: list[dict[str, Any]] = []
    possible_conditions: list[str] = []
    followups: list[str] = []
    patient_summaries: list[str] = []
    doctor_notes: list[str] = []
    red_flags: list[str] = []

    for row in conditions:
        if not isinstance(row, dict):
            continue
        sig = _signals(row)
        if not sig or not any(s in merged_low for s in sig):
            continue
        matched_conditions.append(
            {
                "id": str(row.get("id") or "").strip(),
                "display_name_ru": str(row.get("display_name_ru") or "").strip(),
            }
        )
        possible_conditions.append(str(row.get("display_name_ru") or row.get("id") or "").strip())
        followups.extend([str(x).strip() for x in (row.get("followup") or []) if str(x).strip()])
        patient_summaries.append(str(row.get("patient_safe_summary") or "").strip())
        doctor_notes.append(str(row.get("doctor_notes") or "").strip())
        red_flags.extend([str(x).strip() for x in (row.get("red_flags") or []) if str(x).strip()])

    for row in clusters:
        if not isinstance(row, dict):
            continue
        sig = _signals(row)
        if not sig or not any(s in merged_low for s in sig):
            continue
        matched_clusters.append(
            {
                "id": str(row.get("id") or "").strip(),
                "display_name_ru": str(row.get("display_name_ru") or "").strip(),
            }
        )
        followups.extend([str(x).strip() for x in (row.get("followup") or []) if str(x).strip()])
        patient_summaries.append(str(row.get("patient_safe_summary") or "").strip())
        doctor_notes.append(str(row.get("doctor_notes") or "").strip())

    for row in mediators:
        if not isinstance(row, dict):
            continue
        sig = _signals(row)
        if not sig or not any(s in merged_low for s in sig):
            continue
        matched_mediators.append(
            {
                "id": str(row.get("id") or "").strip(),
                "display_name_ru": str(row.get("display_name_ru") or "").strip(),
            }
        )
        doctor_notes.append(str(row.get("doctor_notes") or "").strip())

    for row in patterns:
        if not isinstance(row, dict):
            continue
        sig = _signals(row)
        if not sig or not any(s in merged_low for s in sig):
            continue
        matched_patterns.append(
            {
                "id": str(row.get("id") or "").strip(),
                "display_name_ru": str(row.get("display_name_ru") or "").strip(),
            }
        )
        possible_conditions.append(str(row.get("display_name_ru") or row.get("id") or "").strip())
        followups.extend([str(x).strip() for x in (row.get("followup") or []) if str(x).strip()])
        patient_summaries.append(str(row.get("patient_safe_summary") or "").strip())
        doctor_notes.append(str(row.get("doctor_notes") or "").strip())
        red_flags.extend([str(x).strip() for x in (row.get("red_flags") or []) if str(x).strip()])

    return {
        "matched_conditions": matched_conditions[:10],
        "matched_clusters": matched_clusters[:10],
        "matched_mediators": matched_mediators[:16],
        "matched_patterns": matched_patterns[:10],
        "possible_conditions": _dedup_texts(possible_conditions),
        "followup_questions": _dedup_texts(followups),
        "patient_safe_summaries": _dedup_texts(patient_summaries),
        "doctor_notes": _dedup_texts(doctor_notes),
        "red_flags": _dedup_texts(red_flags),
    }


def _extract_symptom_intelligence_layer(merged_low: str) -> dict[str, Any]:
    payload = _load_symptom_intelligence_module()
    registry = payload.get("symptom_registry") or []
    clusters = payload.get("clusters") or []
    patterns = payload.get("patterns") or []
    module_red_flags = [str(x).strip() for x in (payload.get("red_flags") or []) if str(x).strip()]
    if not isinstance(registry, list):
        registry = []
    if not isinstance(clusters, list):
        clusters = []
    if not isinstance(patterns, list):
        patterns = []

    def _aliases(sym: dict[str, Any]) -> list[str]:
        out: list[str] = []
        sid = str(sym.get("id") or "").strip().lower()
        name = str(sym.get("name_ru") or "").strip().lower()
        if sid:
            out.append(sid.replace("_", " "))
        if name:
            out.append(name)
        for a in (sym.get("aliases") or []):
            s = str(a or "").strip().lower()
            if s:
                out.append(s)
        return _dedup_texts(out)

    matched_symptoms: list[dict[str, Any]] = []
    matched_ids: set[str] = set()
    categories: set[str] = set()
    for row in registry:
        if not isinstance(row, dict):
            continue
        aliases = _aliases(row)
        if not aliases:
            continue
        if not any(_contains_ru_phrase(merged_low, a) for a in aliases):
            continue
        sid = str(row.get("id") or "").strip()
        if not sid:
            continue
        matched_ids.add(sid)
        categories.add(str(row.get("category") or "").strip())
        matched_symptoms.append(
            {
                "id": sid,
                "name_ru": str(row.get("name_ru") or "").strip(),
                "category": str(row.get("category") or "").strip(),
            }
        )

    detected_clusters: list[dict[str, Any]] = []
    detected_cluster_ids: set[str] = set()
    for row in clusters:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "").strip()
        if not cid:
            continue
        symptom_ids = {str(x).strip() for x in (row.get("symptom_ids") or []) if str(x).strip()}
        if not symptom_ids:
            continue
        min_count = int(row.get("min_match_count") or 1)
        hit_count = len(symptom_ids & matched_ids)
        if hit_count < max(1, min_count):
            continue
        detected_cluster_ids.add(cid)
        detected_clusters.append(
            {
                "id": cid,
                "name_ru": str(row.get("name_ru") or "").strip(),
                "matched_count": hit_count,
            }
        )

    system_count = len([x for x in categories if x])

    detected_patterns: list[dict[str, Any]] = []
    followup_questions: list[str] = []
    patient_summaries: list[str] = []
    doctor_notes: list[str] = []
    possible_conditions: list[str] = []
    red_flags: list[str] = []

    for row in patterns:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("id") or "").strip()
        if not pid:
            continue
        min_systems = int(row.get("min_systems") or 1)
        if system_count < min_systems:
            continue
        req_clusters_any = {str(x).strip() for x in (row.get("required_clusters_any") or []) if str(x).strip()}
        if req_clusters_any and not (req_clusters_any & detected_cluster_ids):
            continue
        req_kw_any = [str(x).strip().lower() for x in (row.get("required_keywords_any") or []) if str(x).strip()]
        if req_kw_any and not any(_contains_ru_phrase(merged_low, kw) for kw in req_kw_any):
            continue
        detected_patterns.append(
            {
                "id": pid,
                "name_ru": str(row.get("name_ru") or "").strip(),
            }
        )
        followup_questions.extend([str(x).strip() for x in (row.get("followup_questions") or []) if str(x).strip()])
        ps = str(row.get("patient_safe_summary") or "").strip()
        dn = str(row.get("doctor_notes") or "").strip()
        if ps:
            patient_summaries.append(ps)
        if dn:
            doctor_notes.append(dn)
        possible_conditions.append(str(row.get("name_ru") or pid).strip())

    for row in registry:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id") or "").strip()
        if not sid or sid not in matched_ids:
            continue
        if bool(row.get("red_flag")):
            nm = str(row.get("name_ru") or sid).strip()
            red_flags.append(nm + " — требуется срочная очная оценка/неотложка.")

    red_flags.extend(module_red_flags)

    return {
        "matched_symptoms": matched_symptoms[:25],
        "detected_clusters": detected_clusters[:10],
        "detected_patterns": detected_patterns[:8],
        "system_count": system_count,
        "possible_conditions": _dedup_texts(possible_conditions),
        "followup_questions": _dedup_texts(followup_questions),
        "patient_safe_summaries": _dedup_texts(patient_summaries),
        "doctor_notes": _dedup_texts(doctor_notes),
        "red_flags": _dedup_texts(red_flags),
    }


def _extract_causal_engine_layer(merged_low: str) -> dict[str, Any]:
    payload = _load_causal_engine_module()
    predisposition_rows = payload.get("predisposition_registry") or []
    root_rows = payload.get("root_cause_registry") or []
    trigger_rows = payload.get("trigger_registry") or []
    special_rows = payload.get("special_triggers") or []
    timeline = payload.get("timeline_signals") or {}
    default_questions = [str(x).strip() for x in (payload.get("default_followup_questions") or []) if str(x).strip()]
    if not isinstance(predisposition_rows, list):
        predisposition_rows = []
    if not isinstance(root_rows, list):
        root_rows = []
    if not isinstance(trigger_rows, list):
        trigger_rows = []
    if not isinstance(special_rows, list):
        special_rows = []
    if not isinstance(timeline, dict):
        timeline = {}

    def _match_registry(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            aliases = [str(x).strip().lower() for x in (row.get("aliases") or []) if str(x).strip()]
            aliases.append(str(row.get("id") or "").strip().lower())
            aliases.append(str(row.get("name_ru") or "").strip().lower())
            aliases = [x for x in aliases if x]
            if not aliases:
                continue
            if not any(_contains_ru_phrase(merged_low, a) for a in aliases):
                continue
            out.append(
                {
                    "id": str(row.get("id") or "").strip(),
                    "name_ru": str(row.get("name_ru") or "").strip(),
                    "patient_safe_summary": str(row.get("patient_safe_summary") or "").strip(),
                    "doctor_notes": str(row.get("doctor_notes") or "").strip(),
                }
            )
        return out

    predisposition = _match_registry(predisposition_rows)
    root_causes = _match_registry(root_rows)
    triggers = _match_registry(trigger_rows)

    special_triggers: list[dict[str, Any]] = []
    for row in special_rows:
        if not isinstance(row, dict):
            continue
        cond = [str(x).strip().lower() for x in (row.get("conditions_any") or []) if str(x).strip()]
        if not cond:
            continue
        if not any(_contains_ru_phrase(merged_low, c) for c in cond):
            continue
        special_triggers.append(
            {
                "id": str(row.get("id") or "").strip(),
                "name_ru": str(row.get("name_ru") or "").strip(),
                "patient_safe_summary": str(row.get("patient_safe_summary") or "").strip(),
                "doctor_notes": str(row.get("doctor_notes") or "").strip(),
            }
        )

    early_markers = [str(x).strip().lower() for x in (timeline.get("early_signs") or []) if str(x).strip()]
    trigger_markers = [str(x).strip().lower() for x in (timeline.get("trigger_events") or []) if str(x).strip()]
    decomp_markers = [str(x).strip().lower() for x in (timeline.get("decompensation") or []) if str(x).strip()]

    early_hits = [x for x in early_markers if _contains_ru_phrase(merged_low, x)]
    trigger_hits = [x for x in trigger_markers if _contains_ru_phrase(merged_low, x)]
    decomp_hits = [x for x in decomp_markers if _contains_ru_phrase(merged_low, x)]

    predisposition_score = min(
        100,
        len(predisposition) * 15 + len(root_causes) * 10 + len(triggers) * 8 + len(special_triggers) * 12 + len(early_hits) * 8,
    )

    trigger_detected = _dedup_texts(
        [str(x.get("id") or "").strip() for x in triggers if str(x.get("id") or "").strip()]
        + [str(x.get("id") or "").strip() for x in special_triggers if str(x.get("id") or "").strip()]
    )
    trigger_event = trigger_hits[0] if trigger_hits else ""
    if not trigger_event and trigger_detected:
        trigger_event = str(trigger_detected[0]).strip()

    cause_model = {
        "predisposition": [x.get("id") for x in predisposition if x.get("id")],
        "root_causes": [x.get("id") for x in root_causes if x.get("id")],
        "triggers": [x.get("id") for x in triggers if x.get("id")],
        "modifiers": [x.get("id") for x in special_triggers if x.get("id")],
    }
    timeline_engine = {
        "early_signs": early_hits[:5],
        "compensation_phase": bool(early_hits) and not bool(decomp_hits),
        "trigger_event": trigger_event,
        "decompensation": bool(decomp_hits),
    }

    followup_questions = list(default_questions)
    if not early_hits:
        followup_questions.append("Были ли похожие симптомы раньше (в детстве/подростковом возрасте)?")
    if not trigger_hits:
        followup_questions.append("После какого события стало заметно хуже?")
    if "PHENOL_SENSITIVITY" not in trigger_detected:
        followup_questions.append("Есть ли реакция на запахи, косметику или бытовую химию?")
    if "ANTIBIOTICS" not in trigger_detected:
        followup_questions.append("Были ли частые курсы антибиотиков (особенно в детстве)?")
    if "STRESS" not in trigger_detected:
        followup_questions.append("Есть ли связь ухудшений со стрессом или недосыпом?")
    if "HORMONAL_CHANGE" not in trigger_detected:
        followup_questions.append("Есть ли усиление симптомов перед менструацией/на гормональных фазах?")

    patient_summaries = [str(x.get("patient_safe_summary") or "").strip() for x in predisposition + special_triggers if str(x.get("patient_safe_summary") or "").strip()]
    if str(payload.get("patient_safe_summary") or "").strip():
        patient_summaries.append(str(payload.get("patient_safe_summary") or "").strip())
    doctor_notes = [str(x.get("doctor_notes") or "").strip() for x in predisposition + root_causes + triggers + special_triggers if str(x.get("doctor_notes") or "").strip()]
    if str(payload.get("doctor_notes") or "").strip():
        doctor_notes.append(str(payload.get("doctor_notes") or "").strip())

    return {
        "cause_model": cause_model,
        "predisposition_registry_hits": predisposition[:10],
        "root_cause_hits": root_causes[:12],
        "trigger_hits": triggers[:12],
        "special_trigger_hits": special_triggers[:8],
        "trigger_detected": trigger_detected[:12],
        "predisposition_score": int(predisposition_score),
        "timeline_engine": timeline_engine,
        "followup_questions": _dedup_texts(followup_questions),
        "patient_safe_summaries": _dedup_texts(patient_summaries),
        "doctor_notes": _dedup_texts(doctor_notes),
    }


def _extract_non_drug_engine_layer(
    merged_low: str,
    symptom_intelligence_layer: dict[str, Any],
    causal_engine_layer: dict[str, Any],
) -> dict[str, Any]:
    payload = _load_non_drug_engine_module()
    diet_rules = payload.get("diet_rules") or {}
    digestion = payload.get("digestion_support") or {}
    detox = payload.get("detox") or {}
    circulation = payload.get("circulation") or {}
    ct_support = payload.get("connective_tissue_support") or {}
    lifestyle = payload.get("lifestyle") or {}
    expected_templates = [str(x).strip() for x in (payload.get("expected_effect_templates") or []) if str(x).strip()]
    if not isinstance(diet_rules, dict):
        diet_rules = {}
    if not isinstance(digestion, dict):
        digestion = {}
    if not isinstance(detox, dict):
        detox = {}
    if not isinstance(circulation, dict):
        circulation = {}
    if not isinstance(ct_support, dict):
        ct_support = {}
    if not isinstance(lifestyle, dict):
        lifestyle = {}

    def _in_text(items: list[str]) -> bool:
        return any(_contains_ru_phrase(merged_low, str(x).strip().lower()) for x in (items or []) if str(x).strip())

    detected_patterns = {
        str((x or {}).get("id") or "").strip()
        for x in (symptom_intelligence_layer.get("detected_patterns") or [])
        if str((x or {}).get("id") or "").strip()
    }
    detected_clusters = {
        str((x or {}).get("id") or "").strip()
        for x in (symptom_intelligence_layer.get("detected_clusters") or [])
        if str((x or {}).get("id") or "").strip()
    }
    cause_model = dict(causal_engine_layer.get("cause_model") or {})
    cause_mods = {str(x).strip() for x in (cause_model.get("modifiers") or []) if str(x).strip()}
    cause_preds = {str(x).strip() for x in (cause_model.get("predisposition") or []) if str(x).strip()}
    cause_triggers = {str(x).strip() for x in (causal_engine_layer.get("trigger_detected") or []) if str(x).strip()}

    diet_recommendations: list[str] = []
    what_to_remove: list[str] = []
    what_to_add: list[str] = []
    lifestyle_recommendations: list[str] = []
    digestion_actions: list[str] = []
    detox_actions: list[str] = []
    circulation_actions: list[str] = []
    expected_effect: list[str] = []

    # Base diet logic.
    for rule_id in ("FRESH_FOOD_ONLY", "LOW_HISTAMINE_DIET", "ADDITIVE_FREE"):
        rule = diet_rules.get(rule_id) or {}
        desc = str(rule.get("description") or "").strip()
        if desc:
            diet_recommendations.append(desc)
        what_to_remove.extend([str(x).strip() for x in (rule.get("what_to_remove") or []) if str(x).strip()])
        what_to_add.extend([str(x).strip() for x in (rule.get("what_to_add") or []) if str(x).strip()])

    if "HISTAMINE_LIKE_PATTERN" in detected_patterns or {"SKIN_HISTAMINE_CLUSTER", "GI_CLUSTER", "NEURO_PSYCHO_CLUSTER"} <= detected_clusters:
        rule = diet_rules.get("INTERMITTENT_FASTING") or {}
        if str(rule.get("description") or "").strip():
            diet_recommendations.append(str(rule.get("description") or "").strip())
        what_to_add.extend([str(x).strip() for x in (rule.get("what_to_add") or []) if str(x).strip()])

    if _contains_ru_phrase(merged_low, "сахар") or "GUT_TRIGGER" in cause_mods or "MICROBIOME_IMBALANCE" in cause_preds:
        rule = diet_rules.get("NO_SUGAR") or {}
        if str(rule.get("description") or "").strip():
            diet_recommendations.append(str(rule.get("description") or "").strip())
        what_to_remove.extend([str(x).strip() for x in (rule.get("what_to_remove") or []) if str(x).strip()])

    # Digestion support.
    if _in_text([str(x).strip().lower() for x in (digestion.get("activation_signals") or [])]) or "GI_CLUSTER" in detected_clusters:
        digestion_actions.extend([str(x).strip() for x in (digestion.get("actions") or []) if str(x).strip()])

    # Detox support.
    detox_needed = bool(
        _in_text([str(x).strip().lower() for x in (detox.get("activation_signals") or [])])
        or "PHENOL_SENSITIVITY" in cause_mods
        or "CHEMICAL_EXPOSURE" in cause_triggers
        or "DETOX_IMPAIRMENT" in {str(x).strip() for x in (cause_model.get("root_causes") or []) if str(x).strip()}
    )
    if detox_needed:
        detox_actions.extend([str(x).strip() for x in (detox.get("blocks") or []) if str(x).strip()])
        detox_actions.extend([str(x).strip() for x in (detox.get("sorbents_examples") or []) if str(x).strip()])

    # Circulation / POTS support.
    if (
        "ORTHOSTATIC_PATTERN" in detected_patterns
        or "ORTHOSTATIC_TRIGGER" in cause_mods
        or _in_text([str(x).strip().lower() for x in (circulation.get("activation_signals") or [])])
    ):
        circulation_actions.extend([str(x).strip() for x in (circulation.get("pots_support") or []) if str(x).strip()])

    # Connective tissue support.
    if "CONNECTIVE_TISSUE_DYSPLASIA" in cause_preds or _in_text([str(x).strip().lower() for x in (ct_support.get("activation_signals") or [])]):
        what_to_add.extend([str(x).strip() for x in (ct_support.get("actions") or []) if str(x).strip()])

    # Lifestyle.
    lifestyle_recommendations.extend([str(x).strip() for x in (lifestyle.get("stress_sleep") or []) if str(x).strip()])
    if circulation_actions or detox_needed:
        lifestyle_recommendations.extend([str(x).strip() for x in (lifestyle.get("lymph_circulation") or []) if str(x).strip()])

    if diet_recommendations or digestion_actions or detox_actions or circulation_actions:
        expected_effect.extend(expected_templates)

    non_drug_plan = {
        "diet": {
            "fresh_food_only": True,
            "low_histamine": True,
            "intermittent_fasting": "recommended" if "HISTAMINE_LIKE_PATTERN" in detected_patterns else "consider",
            "no_sugar": ("NO_SUGAR" in diet_rules) and (detox_needed or "GUT_TRIGGER" in cause_mods),
            "additive_free": True,
        },
        "lifestyle": _dedup_texts(lifestyle_recommendations)[:8],
        "digestion_support": _dedup_texts(digestion_actions)[:6],
        "detox": _dedup_texts(detox_actions)[:8],
        "circulation": _dedup_texts(circulation_actions)[:6],
        "restrictions": _dedup_texts(what_to_remove)[:10],
    }

    return {
        "non_drug_plan": non_drug_plan,
        "diet_recommendations": _dedup_texts(diet_recommendations)[:8],
        "lifestyle_recommendations": _dedup_texts(lifestyle_recommendations)[:8],
        "detox_needed": bool(detox_needed),
        "diet": _dedup_texts(diet_recommendations)[:8],
        "what_to_remove": _dedup_texts(what_to_remove)[:12],
        "what_to_add": _dedup_texts(what_to_add)[:12],
        "lifestyle": _dedup_texts(lifestyle_recommendations)[:8],
        "detox": _dedup_texts(detox_actions)[:8],
        "expected_effect": _dedup_texts(expected_effect)[:6],
        "patient_safe_summary": str(payload.get("patient_safe_summary") or "").strip(),
        "doctor_notes": str(payload.get("doctor_notes") or "").strip(),
    }


def _extract_nutraceutical_engine_layer(
    merged_low: str,
    symptom_intelligence_layer: dict[str, Any],
    causal_engine_layer: dict[str, Any],
    non_drug_engine_layer: dict[str, Any],
) -> dict[str, Any]:
    payload = _load_nutraceutical_engine_module()
    core_rules = dict(payload.get("core_rules") or {})
    target_blocks = payload.get("target_blocks") or []
    followups = [str(x).strip() for x in (payload.get("followup_questions") or []) if str(x).strip()]
    rx_only = [str(x).strip() for x in (payload.get("prescription_options_doctor_only") or []) if str(x).strip()]
    red_flags = [str(x).strip() for x in (payload.get("red_flags") or []) if str(x).strip()]
    if not isinstance(target_blocks, list):
        target_blocks = []

    pattern_ids = {
        str((x or {}).get("id") or "").strip().lower()
        for x in (symptom_intelligence_layer.get("detected_patterns") or [])
        if str((x or {}).get("id") or "").strip()
    }
    cluster_ids = {
        str((x or {}).get("id") or "").strip().lower()
        for x in (symptom_intelligence_layer.get("detected_clusters") or [])
        if str((x or {}).get("id") or "").strip()
    }
    cause_model = dict(causal_engine_layer.get("cause_model") or {})
    cause_nodes = {
        str(x).strip().lower()
        for x in (
            (cause_model.get("predisposition") or [])
            + (cause_model.get("root_causes") or [])
            + (cause_model.get("triggers") or [])
            + (cause_model.get("modifiers") or [])
            + (causal_engine_layer.get("trigger_detected") or [])
        )
        if str(x).strip()
    }
    non_drug_ready = bool(
        (non_drug_engine_layer.get("diet_recommendations") or [])
        or (non_drug_engine_layer.get("lifestyle_recommendations") or [])
    )

    selected_blocks: list[dict[str, Any]] = []
    nutraceutical_options: list[str] = []
    patient_texts: list[str] = []
    doctor_texts: list[str] = []

    for row in target_blocks:
        if not isinstance(row, dict):
            continue
        when_to_use = [str(x).strip().lower() for x in (row.get("when_to_use") or []) if str(x).strip()]
        if when_to_use:
            hit = False
            for token in when_to_use:
                if token in pattern_ids or token in cluster_ids or token in cause_nodes:
                    hit = True
                    break
                if token in merged_low:
                    hit = True
                    break
            if not hit:
                continue
        bid = str(row.get("id") or "").strip()
        if not bid:
            continue
        options = [str(x).strip() for x in (row.get("options") or []) if str(x).strip()]
        nutraceutical_options.extend(options)
        pt = str(row.get("patient_text") or "").strip()
        dt = str(row.get("doctor_text") or "").strip()
        if pt:
            patient_texts.append(pt)
        if dt:
            doctor_texts.append(dt)
        selected_blocks.append(
            {
                "id": bid,
                "options": options[:8],
                "patient_text": pt,
                "doctor_text": dt,
            }
        )

    # Always include caution logic in output when any options selected.
    caution_logic = {
        "start_low_go_slow": str(core_rules.get("start_low_go_slow") or "").strip(),
        "split_dosing": str(core_rules.get("split_dosing") or "").strip(),
        "paradoxical_reaction": str(core_rules.get("paradoxical_reaction") or "").strip(),
        "sensitivity_logic": str(core_rules.get("sensitivity_logic") or "").strip(),
        "apply_only_after_non_drug": bool(non_drug_ready),
    }

    # Keep patient output conservative and optional.
    patient_safe_steps: list[str] = []
    if nutraceutical_options:
        patient_safe_steps.append("Дополнительные средства обсуждать только после базового плана питания/режима.")
        patient_safe_steps.append("Новый продукт вводить по одному, с малой дозы и наблюдением переносимости.")
    patient_safe_steps.extend(patient_texts[:2])

    return {
        "selected_blocks": selected_blocks[:6],
        "nutraceutical_options": _dedup_texts(nutraceutical_options)[:16],
        "cautious_medication_start": caution_logic,
        "patient_safe_steps": _dedup_texts(patient_safe_steps)[:5],
        "followup_questions": _dedup_texts(followups)[:4],
        "doctor_only_options": rx_only[:12],
        "red_flags": red_flags[:4],
        "patient_safe_summary": str(payload.get("patient_safe_summary") or "").strip(),
        "doctor_notes": str(payload.get("doctor_notes") or "").strip(),
        "non_drug_required_first": bool(non_drug_ready),
    }


def _extract_amino_engine_layer(
    merged_low: str,
    symptom_intelligence_layer: dict[str, Any],
    causal_engine_layer: dict[str, Any],
) -> dict[str, Any]:
    payload = _load_amino_engine_module()
    registry = payload.get("amino_registry") or {}
    patterns = payload.get("patterns") or []
    cause_links = payload.get("cause_links") or {}
    pre_warnings = payload.get("preanalytic_warnings") or []
    plan_mapping = payload.get("plan_mapping") or {}
    if not isinstance(registry, dict):
        registry = {}
    if not isinstance(patterns, list):
        patterns = []
    if not isinstance(cause_links, dict):
        cause_links = {}
    if not isinstance(pre_warnings, list):
        pre_warnings = []
    if not isinstance(plan_mapping, dict):
        plan_mapping = {}

    amino_hits: list[dict[str, Any]] = []
    for group_name in ("essential", "non_essential"):
        for row in (registry.get(group_name) or []):
            if not isinstance(row, dict):
                continue
            aliases = [str(x).strip().lower() for x in (row.get("aliases") or []) if str(x).strip()]
            if not aliases:
                continue
            if not any(_contains_ru_phrase(merged_low, a) for a in aliases):
                continue
            amino_hits.append(
                {
                    "id": str(row.get("id") or "").strip(),
                    "name_ru": str(row.get("name_ru") or "").strip(),
                    "group": group_name,
                }
            )

    pattern_hits: list[dict[str, Any]] = []
    linked_causes: list[str] = []
    plan_actions: list[str] = []
    patient_summaries: list[str] = []
    doctor_notes: list[str] = []

    symptom_patterns = {
        str((x or {}).get("id") or "").strip().lower()
        for x in (symptom_intelligence_layer.get("detected_patterns") or [])
        if str((x or {}).get("id") or "").strip()
    }
    cause_model = dict(causal_engine_layer.get("cause_model") or {})
    cause_nodes = {
        str(x).strip().lower()
        for x in (
            (cause_model.get("predisposition") or [])
            + (cause_model.get("root_causes") or [])
            + (cause_model.get("triggers") or [])
            + (cause_model.get("modifiers") or [])
        )
        if str(x).strip()
    }

    for row in patterns:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("id") or "").strip()
        if not pid:
            continue
        triggers_any = [str(x).strip().lower() for x in (row.get("triggers_any") or []) if str(x).strip()]
        hit = any(_contains_ru_phrase(merged_low, t) for t in triggers_any)

        # Bridge from existing engines when text is not explicit.
        if not hit and pid == "DETOX_PATTERN":
            hit = ("detox_impairment" in cause_nodes) or ("phenol_sensitivity" in cause_nodes)
        if not hit and pid == "NEURO_EXCITATION_PATTERN":
            hit = ("histamine_like_pattern" in symptom_patterns) or ("orthostatic_pattern" in symptom_patterns)
        if not hit and pid == "COLLAGEN_WEAKNESS_PATTERN":
            hit = "connective_tissue_dysplasia" in cause_nodes
        if not hit and pid == "ENERGY_DEFICIT_PATTERN":
            hit = ("mitochondrial_dysfunction" in cause_nodes) or ("stress_load_pattern" in cause_nodes)

        if not hit:
            continue
        pattern_hits.append(
            {
                "id": pid,
                "name_ru": str(row.get("name_ru") or "").strip(),
            }
        )
        linked_causes.extend([str(x).strip() for x in (cause_links.get(pid) or []) if str(x).strip()])
        plan_actions.extend([str(x).strip() for x in (plan_mapping.get(pid) or []) if str(x).strip()])
        ps = str(row.get("patient_safe_summary") or "").strip()
        dn = str(row.get("doctor_notes") or "").strip()
        if ps:
            patient_summaries.append(ps)
        if dn:
            doctor_notes.append(dn)

    warnings: list[str] = []
    for row in pre_warnings:
        if not isinstance(row, dict):
            continue
        signals = [str(x).strip().lower() for x in (row.get("signals") or []) if str(x).strip()]
        if signals and any(_contains_ru_phrase(merged_low, s) for s in signals):
            w = str(row.get("warning") or "").strip()
            if w:
                warnings.append(w)

    detox_status = "support_needed" if any((x.get("id") or "") == "DETOX_PATTERN" for x in pattern_hits) else "stable_or_unknown"
    neuro_balance = "excitation_risk" if any((x.get("id") or "") == "NEURO_EXCITATION_PATTERN" for x in pattern_hits) else "balanced_or_unknown"
    energy_status = "deficit_risk" if any((x.get("id") or "") == "ENERGY_DEFICIT_PATTERN" for x in pattern_hits) else "adequate_or_unknown"
    metabolic_state = "amino_imbalance_likely" if pattern_hits else "limited_signal"

    return {
        "amino_hits": amino_hits[:20],
        "amino_patterns": pattern_hits[:8],
        "linked_causes": _dedup_texts(linked_causes),
        "plan_actions": _dedup_texts(plan_actions),
        "preanalytic_warnings": _dedup_texts(warnings),
        "metabolic_state": metabolic_state,
        "detox_status": detox_status,
        "neuro_balance": neuro_balance,
        "energy_status": energy_status,
        "patient_safe_summary": str(payload.get("patient_safe_summary") or "").strip(),
        "doctor_notes": str(payload.get("doctor_notes") or "").strip(),
        "followup_questions": [
            "Аминокислотный профиль сдавался натощак и с соблюдением преаналитики?",
            "Есть ли признаки перевозбуждения (тревога/бессонница) и дефицита энергии одновременно?",
        ],
    }


ORGANIC_ACIDS_FORBIDDEN_FOOD_IDS = frozenset({"chocolate", "citrus", "wine", "beans"})

def build_food_trigger_context(user_text: str, document_text: str = "", lab_type: str | None = None) -> dict[str, Any]:
    merged = ((user_text or "") + "\n" + (document_text or "")).strip()
    merged_low = merged.lower()
    matched_foods = _match_food_ids(merged)
    if lab_type == "organic_acids":
        matched_foods = {f for f in matched_foods if f.lower() not in ORGANIC_ACIDS_FORBIDDEN_FOOD_IDS}
    symptoms = _detect_symptoms(merged)
    mcas_signal = _has_mcas_overlap_signals(merged_low)
    symptom_signal = _has_symptom_intelligence_signals(merged_low)
    causal_signal = _has_causal_engine_signals(merged_low)
    non_drug_signal = _has_non_drug_engine_signals(merged_low)
    nutraceutical_signal = _has_nutraceutical_engine_signals(merged_low)
    amino_signal = _has_amino_engine_signals(merged_low)
    if not matched_foods and not symptoms and not mcas_signal and not symptom_signal and not causal_signal and not non_drug_signal and not nutraceutical_signal and not amino_signal:
        return {}

    foods_payload = _load_foods()
    compounds_payload = _load_compounds()
    matched_food_items: list[dict[str, Any]] = []
    matched_compound_ids: set[str] = set()
    followup_questions: list[str] = []
    safe_recommendations: list[str] = []
    probable_conditions: list[str] = []
    for fid in sorted(matched_foods):
        item = foods_payload.get(fid) or {}
        matched_food_items.append(
            {
                "id": fid,
                "aliases": item.get("aliases") or [],
                "triggered_symptoms": item.get("triggered_symptoms") or [],
                "possible_compounds": item.get("possible_compounds") or [],
                "typical_onset_time": item.get("typical_onset_time") or "",
            }
        )
        for c in (item.get("possible_compounds") or []):
            cs = str(c).strip().lower()
            if cs:
                matched_compound_ids.add(cs)
        followup_questions.extend([str(x).strip() for x in (item.get("questions_to_ask") or []) if str(x).strip()])
        safe_recommendations.extend([str(x).strip() for x in (item.get("safe_recommendations") or []) if str(x).strip()])
        probable_conditions.extend([str(x).strip() for x in (item.get("common_conditions_associated") or []) if str(x).strip()])

    symptom_links: list[dict[str, Any]] = []
    for link in _load_symptom_links():
        sname = str(link.get("symptom") or "").strip().lower()
        if not sname:
            continue
        if sname in symptoms or (sname == "headache" and "migraine" in symptoms):
            symptom_links.append(link)
            for it in (link.get("possible_food_triggers") or []):
                if not isinstance(it, dict):
                    continue
                c = str(it.get("compound") or "").strip().lower()
                if c:
                    matched_compound_ids.add(c)

    pattern_matches: list[dict[str, Any]] = []
    for p in _load_trigger_patterns():
        conditions = [str(x).strip().lower() for x in (p.get("conditions") or []) if str(x).strip()]
        if not conditions:
            continue
        ok = True
        for cond in conditions:
            if cond == "onset_after_food":
                if not any(k in merged.lower() for k in ("после", "после еды", "после того как", "через")):
                    ok = False
            if "headache" in cond and "headache" not in symptoms and "migraine" not in symptoms:
                ok = False
        if ok:
            pattern_matches.append(
                {
                    "pattern_id": p.get("pattern_id"),
                    "possible_causes": p.get("possible_causes") or [],
                    "suggested_questions": p.get("suggested_questions") or [],
                }
            )
            followup_questions.extend([str(x).strip() for x in (p.get("suggested_questions") or []) if str(x).strip()])

    gut_matches: list[dict[str, Any]] = []
    for g in _load_gut_trigger_patterns():
        aliases = [str(x).strip() for x in (g.get("aliases") or []) if str(x).strip()]
        if not aliases:
            continue
        if not any(_match_alias(merged_low, a) for a in aliases):
            continue
        gut_matches.append(g)
        fid = str(g.get("food_id") or "").strip().lower()
        if fid:
            exists = any(str((x or {}).get("id") or "").strip().lower() == fid for x in matched_food_items)
            if not exists:
                matched_food_items.append(
                    {
                        "id": fid,
                        "aliases": g.get("food_aliases") or [],
                        "triggered_symptoms": ["gi"],
                        "possible_compounds": g.get("compound_ids") or [],
                        "typical_onset_time": "",
                    }
                )
        for cid in (g.get("compound_ids") or []):
            cs = str(cid).strip().lower()
            if cs:
                matched_compound_ids.add(cs)
        followup_questions.extend([str(x).strip() for x in (g.get("followup_questions") or []) if str(x).strip()])
        safe_recommendations.extend([str(x).strip() for x in (g.get("safe_recommendations") or []) if str(x).strip()])
        probable_conditions.extend([str(x).strip() for x in (g.get("possible_conditions") or []) if str(x).strip()])

    histamine_layer = _extract_histamine_layer(merged_low, symptoms)
    for cid in (histamine_layer.get("matched_compound_ids") or []):
        cs = str(cid).strip().lower()
        if cs:
            matched_compound_ids.add(cs)
    followup_questions.extend([str(x).strip() for x in (histamine_layer.get("followup_questions") or []) if str(x).strip()])
    safe_recommendations.extend([str(x).strip() for x in (histamine_layer.get("safe_recommendations") or []) if str(x).strip()])
    probable_conditions.extend([str(x).strip() for x in (histamine_layer.get("possible_conditions") or []) if str(x).strip()])
    pdf_prompt_layer = _extract_pdf_prompt_layer(merged_low)
    followup_questions.extend([str(x).strip() for x in (pdf_prompt_layer.get("followup_questions") or []) if str(x).strip()])
    probable_conditions.extend([str(x).strip() for x in (pdf_prompt_layer.get("possible_conditions") or []) if str(x).strip()])
    safe_recommendations.extend([str(x).strip() for x in (pdf_prompt_layer.get("recommended_tests") or []) if str(x).strip()])
    mcas_comorbid_layer = _extract_mcas_comorbid_layer(merged_low)
    followup_questions.extend([str(x).strip() for x in (mcas_comorbid_layer.get("followup_questions") or []) if str(x).strip()])
    probable_conditions.extend([str(x).strip() for x in (mcas_comorbid_layer.get("possible_conditions") or []) if str(x).strip()])
    safe_recommendations.extend([str(x).strip() for x in (mcas_comorbid_layer.get("patient_safe_summaries") or []) if str(x).strip()])
    safe_recommendations.extend([str(x).strip() for x in (mcas_comorbid_layer.get("red_flags") or []) if str(x).strip()])
    symptom_intelligence_layer = _extract_symptom_intelligence_layer(merged_low)
    followup_questions.extend([str(x).strip() for x in (symptom_intelligence_layer.get("followup_questions") or []) if str(x).strip()])
    probable_conditions.extend([str(x).strip() for x in (symptom_intelligence_layer.get("possible_conditions") or []) if str(x).strip()])
    safe_recommendations.extend([str(x).strip() for x in (symptom_intelligence_layer.get("patient_safe_summaries") or []) if str(x).strip()])
    safe_recommendations.extend([str(x).strip() for x in (symptom_intelligence_layer.get("red_flags") or []) if str(x).strip()])
    causal_engine_layer = _extract_causal_engine_layer(merged_low)
    followup_questions.extend([str(x).strip() for x in (causal_engine_layer.get("followup_questions") or []) if str(x).strip()])
    probable_conditions.extend([str(x).strip() for x in ((causal_engine_layer.get("cause_model") or {}).get("root_causes") or []) if str(x).strip()])
    safe_recommendations.extend([str(x).strip() for x in (causal_engine_layer.get("patient_safe_summaries") or []) if str(x).strip()])
    non_drug_engine_layer = _extract_non_drug_engine_layer(merged_low, symptom_intelligence_layer, causal_engine_layer)
    safe_recommendations.extend([str(x).strip() for x in (non_drug_engine_layer.get("diet_recommendations") or []) if str(x).strip()])
    safe_recommendations.extend([str(x).strip() for x in (non_drug_engine_layer.get("lifestyle_recommendations") or []) if str(x).strip()])
    safe_recommendations.extend([str(x).strip() for x in (non_drug_engine_layer.get("what_to_add") or []) if str(x).strip()])
    nutraceutical_engine_layer = _extract_nutraceutical_engine_layer(
        merged_low,
        symptom_intelligence_layer,
        causal_engine_layer,
        non_drug_engine_layer,
    )
    followup_questions.extend([str(x).strip() for x in (nutraceutical_engine_layer.get("followup_questions") or []) if str(x).strip()])
    safe_recommendations.extend([str(x).strip() for x in (nutraceutical_engine_layer.get("patient_safe_steps") or []) if str(x).strip()])
    amino_engine_layer = _extract_amino_engine_layer(
        merged_low,
        symptom_intelligence_layer,
        causal_engine_layer,
    )
    followup_questions.extend([str(x).strip() for x in (amino_engine_layer.get("followup_questions") or []) if str(x).strip()])
    probable_conditions.extend([str(x).strip() for x in (amino_engine_layer.get("linked_causes") or []) if str(x).strip()])
    safe_recommendations.extend([str(x).strip() for x in (amino_engine_layer.get("plan_actions") or []) if str(x).strip()])
    safe_recommendations.extend([str(x).strip() for x in (amino_engine_layer.get("preanalytic_warnings") or []) if str(x).strip()])

    matched_compounds: list[dict[str, Any]] = []
    for cid in sorted(matched_compound_ids):
        cp = compounds_payload.get(cid)
        if cp:
            matched_compounds.append(
                {
                    "id": cid,
                    "mechanism": cp.get("mechanism"),
                    "associated_symptoms": cp.get("associated_symptoms") or [],
                    "associated_conditions": cp.get("associated_conditions") or [],
                }
            )
            continue
        matched_compounds.append(
            {
                "id": cid,
                "mechanism": "",
                "associated_symptoms": ["gi"],
                "associated_conditions": [],
            }
        )

    def _dedup(items: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for x in items:
            k = x.lower()
            if not x or k in seen:
                continue
            seen.add(k)
            out.append(x)
        return out

    concierge_prompt = _load_text(_CONCIERGE_PROMPT_FILE, "")
    gut_prompt = _load_text(_GUT_CONCIERGE_PROMPT_FILE, "")
    report_prompt = _load_text(_REPORT_PROMPT_FILE, "")

    return {
        "matched_foods": matched_food_items,
        "matched_compounds": matched_compounds,
        "symptom_links": symptom_links,
        "pattern_matches": pattern_matches,
        "gut_trigger_matches": gut_matches,
        "histamine_layer": histamine_layer,
        "pdf_prompt_layer": pdf_prompt_layer,
        "mcas_comorbid_layer": mcas_comorbid_layer,
        "symptom_intelligence_layer": symptom_intelligence_layer,
        "causal_engine_layer": causal_engine_layer,
        "non_drug_engine_layer": non_drug_engine_layer,
        "nutraceutical_engine_layer": nutraceutical_engine_layer,
        "amino_engine_layer": amino_engine_layer,
        "followup_questions": _dedup(followup_questions),
        "safe_recommendations": _dedup(safe_recommendations),
        "possible_conditions": _dedup(probable_conditions),
        "concierge_prompt": (concierge_prompt + ("\n\n" + gut_prompt if gut_prompt else "")).strip(),
        "report_prompt": report_prompt,
    }

