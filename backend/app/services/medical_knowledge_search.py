"""
MedicalKnowledgeSearch: query ingested knowledge; return summary, causes, tests, red flags.
Isolated module. All responses include security disclaimer.
Voice and chat use the same search layer when this module is used.
"""
import json
import re
from pathlib import Path
from typing import Any

from app.services.medical_knowledge_indexer import load_chunks
from app.services.medical_source_ranker import detect_query_domain, rank_sources_for_domain

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
KNOWLEDGE_CACHE = _BACKEND_DIR.parent / "knowledge_cache"

SECURITY_DISCLAIMER = "This information is educational and not a medical diagnosis. Consult a physician."
ONLINE_REFERENCE_LINKS = [
    "https://medlineplus.gov/healthtopics.html",
    "https://www.nice.org.uk/guidance",
    "https://www.cdc.gov/health-topics.html",
    "https://www.who.int/publications/guidelines",
    "https://www.cochranelibrary.com/",
    "https://pubmed.ncbi.nlm.nih.gov/",
    "https://api.fda.gov/drug/label.json?limit=20",
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmode=json&term=clinical+guideline",
]


def _normalize_query(q: str) -> list[str]:
    if not q or not q.strip():
        return []
    s = re.sub(r"[^\w\sа-яёa-z0-9]", " ", q.strip().lower())
    return [w for w in s.split() if len(w) > 1]


def _chunk_score(chunk: dict, words: list[str]) -> int:
    text = (chunk.get("text") or "") + " " + (chunk.get("title") or "") + " " + (chunk.get("topic") or "")
    text = text.lower()
    return sum(1 for w in words if w in text)


def _looks_like_slide_noise(text: str) -> bool:
    low = (text or "").lower()
    noise_keys = (
        "@radevich",
        "radevich",
        "academy of medical",
        "biochemistry",
    )
    return any(k in low for k in noise_keys)


def _split_long_fact_line(text: str) -> list[str]:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s:
        return []
    if len(s) <= 220:
        return [s]
    # Soft split for OCR-heavy paragraphs: keep meaningful short fragments.
    parts = re.split(r"[•;\.\n]+", s)
    out: list[str] = []
    for p in parts:
        p = re.sub(r"\s+", " ", p).strip(" -:;,")
        if not p:
            continue
        if 20 <= len(p) <= 220:
            out.append(p)
    return out[:8]


def _clean_fact_line(text: str) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s:
        return ""
    s = s.strip("•-–— ").strip()
    banned_fragments = (
        "у 14 детей ре-",
        "у 14 детей результаты хроматографического анализа органических кислот",
        "в плане дальнейших исследований",
        "в целях уточнения диагноза намечены",
        "повторное исследование органи",
        "анализ ацилкарнитинов крови",
        "определение ацилкарнитинов",
        "маркерными метаболитами этого заболевания являются",
        "маркерными ме- таболитами этого заболевания являются",
        "субериновая и себациновая кислоты",
        "дефицит одной из них",
        "выше 2,7 +другие метаболиты фенилаланина",
    )
    low = s.lower()
    canon = re.sub(r"[^a-zа-яё0-9]+", "", low)
    if any(b in low for b in banned_fragments):
        return ""
    banned_fragments_canon = (
        "впланедальнейшихисследований",
        "вцеляхуточнениядиагнозанамечены",
        "повторноеисследованиеорганическихкислотвмочеианализацилкарнитиновкрови",
        "определениеацилкарнитинов",
        "анализацилкарнитиновкрови",
        "маркернымиметаболитамиэтогозаболеванияявляются",
        "субериноваяисебациноваякислоты",
        "дефицитоднойизних",
        "выше27другиеметаболитыфенилаланина",
    )
    if any(b in canon for b in banned_fragments_canon):
        return ""
    if low in {"дефицит витамина d", "дефицит витамина d.", "дефицит витамина d:"}:
        return ""
    if _is_machine_blob(s) or _looks_like_slide_noise(s):
        return ""
    # Avoid dumping giant raw OCR blocks into report fields.
    if len(s) > 220:
        return ""
    return s


def _is_metabolic_lab_query(query: str) -> bool:
    low = (query or "").lower()
    keys = (
        "органическ",
        "аминокис",
        "метабол",
        "ацидеми",
        "ацидур",
        "масс-спектр",
        "масс спектр",
        "gc-ms",
        "гх-мс",
        "креатинин",
        "ммоль/моль",
        "дисбиоз",
        "митохонд",
    )
    return any(k in low for k in keys)


def _chunk_source_boost(query: str, chunk: dict) -> int:
    """
    Increase ranking for curated OCR sources on metabolic-lab queries
    so report sections rely on the strongest local OA/AA materials first.
    """
    if not _is_metabolic_lab_query(query):
        return 0
    src = str(chunk.get("source") or "").lower()
    title = str(chunk.get("title") or "").lower()
    text = str(chunk.get("text") or "").lower()[:1200]
    combined = " ".join([src, title, text])
    if "ocr_mass_spec_differential_diagnosis" in combined or "otsenka_mass_spektrometricheskih" in combined:
        return 10
    if "ocr_organic_and_aminoacids" in combined or "органические и аминокислоты" in combined:
        return 8
    if "ocr_aminoacids_help" in combined or "aminoacids_help" in combined:
        return 7
    if "органическ" in combined and "кислот" in combined:
        return 3
    if "аминокис" in combined:
        return 2
    return 0


def _is_machine_blob(text: str) -> bool:
    low = (text or "").lower()
    if not low.strip():
        return True
    if "<!doctype html" in low:
        return True
    if "topic: drugs" in low and ("\"meta\"" in low or "\"results\"" in low):
        return True
    if "openfda" in low and ("{\"meta\"" in low or "\"results\": [" in low):
        return True
    braces = low.count("{") + low.count("}")
    if braces >= 20:
        return True
    return False


def search(query: str, max_results: int = 10, language: str = "") -> dict[str, Any]:
    """
    Search ingested medical knowledge. Returns:
    - summary: short text summary
    - possible_causes: list
    - recommended_tests: list
    - red_flags: list (when to seek urgent care)
    - disclaimer: always present
    """
    result = {
        "summary": "",
        "possible_causes": [],
        "recommended_tests": [],
        "red_flags": [],
        "sources": [],
        "disclaimer": SECURITY_DISCLAIMER,
    }
    words = _normalize_query(query)
    query_domain = detect_query_domain(query or "")
    if not words:
        return result

    chunks = load_chunks()
    if not chunks:
        result["summary"] = "Локальный кэш пока пуст. Используйте проверенные публичные источники ниже и запустите синхронизацию/ингест данных."
        result["sources"] = rank_sources_for_domain(ONLINE_REFERENCE_LINKS, query_domain)[:5]
        return result

    scored = [(c, _chunk_score(c, words) + _chunk_source_boost(query, c)) for c in chunks]
    scored = [(c, s) for c, s in scored if s > 0]
    scored.sort(key=lambda x: x[1], reverse=True)
    selected = [c for c, _ in scored[: max_results * 2]]  # take extra to extract structured fields
    selected = [c for c in selected if not _is_machine_blob(str(c.get("text") or ""))]
    if not selected:
        result["summary"] = "По локальной базе нет прямых совпадений. Проверьте формулировку запроса или используйте источники ниже."
        result["sources"] = rank_sources_for_domain(ONLINE_REFERENCE_LINKS, query_domain)[:5]
        return result

    # Prefer chunks in requested language if any
    if language:
        lang_chunks = [c for c in selected if (c.get("language") or "").lower() == language.lower()]
        if lang_chunks:
            selected = lang_chunks + [c for c in selected if c not in lang_chunks]

    texts = []
    causes = set()
    tests = set()
    for c in selected[:max_results]:
        t = (c.get("text") or "").strip()
        if t:
            texts.append(t)
        title = (c.get("title") or "").strip()
        topic = (c.get("topic") or "").strip()
        title_clean = _clean_fact_line(title)
        topic_clean = _clean_fact_line(topic)
        if title_clean:
            causes.add(title_clean)
        if topic_clean and topic_clean not in ("general", "General"):
            causes.add(topic_clean)
        # Heuristics: lines with "Diagnostic", "симптом", "причина", "тест", "анализ"
        line_candidates = []
        raw_lines = [ln.strip() for ln in t.split("\n") if ln and ln.strip()]
        if len(raw_lines) <= 1 and len(t) > 220:
            line_candidates = _split_long_fact_line(t)
        else:
            line_candidates = raw_lines
        for line in line_candidates:
            line = line.strip()
            if not line:
                continue
            lower = line.lower()
            if "diagnostic:" in lower or "анализ" in lower or "тест" in lower or "оак" in lower or "ттг" in lower:
                test_line = line.replace("Diagnostic:", "").replace("diagnostic:", "").strip()
                test_line = _clean_fact_line(test_line)
                if test_line:
                    tests.add(test_line)
            if "symptom:" in lower or "симптом" in lower:
                cause_line = line.replace("Symptom:", "").replace("symptom:", "").strip()
                cause_line = _clean_fact_line(cause_line)
                if cause_line:
                    causes.add(cause_line)

    # Soft enrichment for metabolic-lab reports:
    # if OCR content is dense and lacks explicit "symptom:" labels,
    # extract short, human-readable clinical hints by keywords.
    if _is_metabolic_lab_query(query) and len(causes) < 8:
        hint_keys = (
            "дефицит",
            "недостаточ",
            "дисбиоз",
            "митохонд",
            "воспал",
            "интокс",
            "витамин",
            "маркер",
            "ацидеми",
            "ацидур",
            "триптофан",
            "глутатион",
            "карнитин",
        )
        for c in selected[:max_results]:
            t = (c.get("text") or "").strip()
            for frag in _split_long_fact_line(t):
                low = frag.lower()
                if not any(k in low for k in hint_keys):
                    continue
                clean_frag = _clean_fact_line(frag)
                if clean_frag:
                    causes.add(clean_frag)
                if len(causes) >= 15:
                    break
            if len(causes) >= 15:
                break

    result["summary"] = "\n\n".join(texts[:3])[:2000] if texts else ""
    result["possible_causes"] = list(causes)[:15]
    result["recommended_tests"] = list(tests)[:15]
    result["red_flags"] = [
        "Severe or sudden worsening of symptoms",
        "Chest pain, shortness of breath, confusion",
        "High fever that does not improve",
        "This information is educational. Consult a physician for diagnosis.",
    ]
    selected_sources = list({c.get("source") for c in selected if c.get("source")})
    ranked_pool = selected_sources + ONLINE_REFERENCE_LINKS
    result["sources"] = rank_sources_for_domain(ranked_pool, query_domain)[:5]
    return result
