"""
Доступ к актуальным данным PubMed (NCBI / NLM) для подкрепления выводов и рекомендаций.
Использует E-utilities без API-ключа. Таймаут и ошибки не блокируют основной поток.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
REQUEST_TIMEOUT = 8


def fetch_article(pmid: str) -> Optional[dict[str, Any]]:
    """
    Получает данные статьи по PMID (PubMed ID).
    Возвращает dict с title, abstract, authors, pub_date, doi, url или None при ошибке.
    """
    if not (pmid or "").strip():
        return None
    pmid = str(pmid).strip()
    try:
        url = f"{BASE_URL}/efetch.fcgi?db=pubmed&id={urllib.parse.quote(pmid)}&retmode=xml"
        req = urllib.request.Request(url, headers={"User-Agent": "HealthApp/1.0"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        logger.debug("PubMed fetch failed for PMID %s: %s", pmid, e)
        return None

    # Простой парсинг XML без внешних зависимостей
    title = _extract_tag(data, "ArticleTitle")
    abstract = _extract_abstract(data)
    pub_date = _extract_pub_date(data)
    authors = _extract_authors(data)
    doi = _extract_doi(data)
    url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""

    if not title and not abstract:
        return None
    return {
        "pmid": pmid,
        "title": title or "",
        "abstract": (abstract or "")[:2000],
        "pub_date": pub_date or "",
        "authors": authors[:5] if authors else [],
        "doi": doi or "",
        "url": url,
    }


def search_pubmed(query: str, max_results: int = 3) -> list[dict[str, Any]]:
    """
    Поиск по PubMed. Возвращает список кратких описаний статей (pmid, title, snippet, url).
    """
    if not (query or "").strip() or max_results < 1:
        return []
    try:
        q = urllib.parse.quote(query.strip())
        url = f"{BASE_URL}/esearch.fcgi?db=pubmed&term={q}&retmax={max_results}&retmode=json&sort=relevance"
        req = urllib.request.Request(url, headers={"User-Agent": "HealthApp/1.0"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as e:
        logger.debug("PubMed search failed: %s", e)
        return []

    id_list = data.get("esearchresult", {}).get("idlist", [])
    if not id_list:
        return []

    # Краткая информация по каждой статье (esummary)
    ids = ",".join(id_list)
    try:
        url2 = f"{BASE_URL}/esummary.fcgi?db=pubmed&id={ids}&retmode=json"
        req2 = urllib.request.Request(url2, headers={"User-Agent": "HealthApp/1.0"})
        with urllib.request.urlopen(req2, timeout=REQUEST_TIMEOUT) as resp2:
            summary = json.loads(resp2.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        return []

    result = []
    for pid in id_list:
        doc = summary.get("result", {}).get(pid, {})
        title = doc.get("title", "")
        pub_date = doc.get("pubdate", "")
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pid}/" if pid else ""
        result.append({
            "pmid": pid,
            "title": title,
            "pub_date": pub_date,
            "url": url,
        })
    return result


def get_evidence_snippet(pmid: str, max_chars: int = 600) -> Optional[str]:
    """
    Формирует короткий текст для вставки в отчёт: «По данным PubMed (PMID: …): …».
    """
    art = fetch_article(pmid)
    if not art:
        return None
    title = (art.get("title") or "").strip()
    abstract = (art.get("abstract") or "").strip()
    year = (art.get("pub_date") or "")[:4]
    if not abstract:
        abstract = title
    if len(abstract) > max_chars:
        abstract = abstract[: max_chars - 3].rsplit(" ", 1)[0] + "..."
    return f"PubMed (PMID:{art.get('pmid')}, {year}): {title}. {abstract}"


def _extract_tag(xml: str, tag: str) -> Optional[str]:
    m = re.search(rf"<{tag}[^>]*>([^<]+)</{tag}>", xml, re.DOTALL | re.IGNORECASE)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def _extract_abstract(xml: str) -> Optional[str]:
    m = re.search(r"<AbstractText[^>]*>([^<]+)</AbstractText>", xml, re.DOTALL | re.IGNORECASE)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def _extract_pub_date(xml: str) -> Optional[str]:
    for tag in ("PubDate", "ArticleDate"):
        m = re.search(rf"<{tag}[^>]*>([^<]+)</{tag}>", xml, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _extract_authors(xml: str) -> list[str]:
    authors = []
    for m in re.finditer(r"<LastName>([^<]+)</LastName>", xml, re.IGNORECASE):
        authors.append(m.group(1).strip())
    return authors


def _extract_doi(xml: str) -> Optional[str]:
    m = re.search(r"ArticleId.*?doi.*?>([^<]+)</ArticleId>", xml, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"<ArticleId IdType=\"doi\">([^<]+)</ArticleId>", xml, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None
