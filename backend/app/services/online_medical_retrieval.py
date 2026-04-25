from __future__ import annotations

import re
from typing import Any

from app.config import get_settings
from app.services.medical_knowledge_search import search as search_local_knowledge
from app.services.medical_source_ranker import detect_query_domain
from app.services.pubmed_lite import fetch_pubmed_article_hints


_RESEARCH_HINT_KEYS = ("исслед", "guideline", "доказ", "протокол", "рекомендац", "pubmed")
_EXPLICIT_SOURCE_KEYS = (
    "источник",
    "источники",
    "доказательств",
    "доказательства",
    "ссылк",
    "гайд",
    "guideline",
    "рекомендац",
    "на основании чего",
)
_EXPANDED_EVIDENCE_KEYS = (
    "доказательств",
    "доказательства",
    "гайд",
    "guideline",
    "протокол",
    "рекомендац",
)


def _build_query(payload: dict[str, Any]) -> str:
    query = " ".join(
        [
            str(payload.get("chief_complaint") or ""),
            str(payload.get("user_message") or ""),
            str(payload.get("conversation_context") or ""),
        ]
    )
    query = re.sub(r"\s+", " ", query).strip()
    return query[:320]


def _wants_research_links(query: str) -> bool:
    low = (query or "").lower()
    return any(k in low for k in _RESEARCH_HINT_KEYS)


def _wants_explicit_sources(query: str) -> bool:
    low = (query or "").lower()
    return any(k in low for k in _EXPLICIT_SOURCE_KEYS)


def _source_request_mode(query: str) -> str:
    low = (query or "").lower()
    if any(k in low for k in _EXPANDED_EVIDENCE_KEYS):
        return "expanded"
    if any(k in low for k in ("источник", "источники", "ссылк")):
        return "compact"
    return "none"


def _domain_why_line(domain: str) -> str:
    dm = (domain or "").strip().lower()
    if dm in ("endocrine", "clinical"):
        return "Почему релевантны: это клинические рекомендации и доказательные базы по эндокринным сценариям."
    if dm == "cardio":
        return "Почему релевантны: это приоритетные клинические источники по сердечно-сосудистым жалобам."
    if dm == "gastro":
        return "Почему релевантны: это профильные гайды и обзоры по ЖКТ-жалобам."
    if dm == "respiratory":
        return "Почему релевантны: это доказательные источники по респираторным состояниям."
    if dm == "neuro":
        return "Почему релевантны: это клинические источники по неврологическим симптомам."
    return "Почему релевантны: это проверенные клинические и доказательные источники по вашему запросу."


def compose_online_reference_tail(payload: dict[str, Any]) -> str:
    """
    Lightweight online-RAG tail:
    - gated by ONLINE_MEDICAL_RAG_ENABLED
    - keeps links to trusted sources only
    - optional PubMed hints when explicitly research-like query
    """
    settings = get_settings()
    if not getattr(settings, "online_medical_rag_enabled", False):
        return ""
    query = _build_query(payload)
    if len(query) < 8:
        return ""
    # Show online links only by explicit user intent ("sources/evidence/guidelines").
    if not _wants_explicit_sources(query):
        return ""
    mode = _source_request_mode(query)
    if mode == "none":
        return ""
    domain = detect_query_domain(query or "")
    allowed_domains = set(getattr(settings, "online_medical_allowed_domains", set()) or set())
    if allowed_domains and domain and domain not in allowed_domains:
        return ""

    configured_max = int(getattr(settings, "online_medical_max_sources", 3) or 3)
    max_sources = 2 if mode == "compact" else max(3, configured_max)
    timeout = float(getattr(settings, "online_medical_timeout_sec", 3.0) or 3.0)

    urls: list[str] = []
    try:
        local = search_local_knowledge(query, max_results=6, language="ru")
        for src in (local or {}).get("sources") or []:
            s = str(src or "").strip()
            if s and s.startswith("http"):
                urls.append(s)
    except Exception:
        pass

    if getattr(settings, "online_medical_pubmed_enabled", False) and _wants_research_links(query):
        try:
            for row in fetch_pubmed_article_hints(query, max_items=2, timeout=timeout):
                u = str((row or {}).get("url") or "").strip()
                if u:
                    urls.append(u)
        except Exception:
            pass

    deduped: list[str] = []
    seen: set[str] = set()
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        deduped.append(u)
        if len(deduped) >= max_sources:
            break

    if not deduped:
        return ""
    lines = "\n".join([f"- {u}" for u in deduped])
    if mode == "expanded":
        return f"Проверенные онлайн-источники по теме:\n{lines}\n{_domain_why_line(domain)}"
    return f"Проверенные онлайн-источники по теме:\n{lines}"

