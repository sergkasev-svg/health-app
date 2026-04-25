"""
Лёгкие подсказки PubMed через официальные E-utilities (JSON), без HTML-скрапинга.

Лимиты: пауза между запросами, короткий timeout, мало статей; отключается PUBMED_HINTS_DISABLED=1.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
_MIN_INTERVAL_SEC = 0.35
_last_call_monotonic = 0.0


def _throttle() -> None:
    global _last_call_monotonic
    now = time.monotonic()
    delta = now - _last_call_monotonic
    if delta < _MIN_INTERVAL_SEC:
        time.sleep(_MIN_INTERVAL_SEC - delta)
    _last_call_monotonic = time.monotonic()


def _http_get_json(url: str, timeout: float) -> dict[str, Any] | None:
    req = urllib.request.Request(url, headers={"User-Agent": "health-app-knowledge-enrichment/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError) as e:
        logger.info("pubmed_lite_request_failed", extra={"error": str(e)[:200]})
        return None


def fetch_pubmed_article_hints(
    query: str,
    *,
    max_items: int = 3,
    timeout: float = 8.0,
) -> list[dict[str, str]]:
    """
    Возвращает до max_items записей: pmid, title (коротко), url на PubMed.
    """
    if os.environ.get("PUBMED_HINTS_DISABLED", "").strip().lower() in ("1", "true", "yes"):
        return []
    q = (query or "").strip()[:240]
    if len(q) < 4:
        return []
    cap = max(1, min(int(max_items or 3), 5))
    api_key = os.environ.get("NCBI_API_KEY", "").strip()
    _throttle()
    params = {
        "db": "pubmed",
        "retmode": "json",
        "retmax": str(cap),
        "sort": "relevance",
        "term": q,
    }
    if api_key:
        params["api_key"] = api_key
    es_url = f"{_ESEARCH}?{urllib.parse.urlencode(params)}"
    es = _http_get_json(es_url, timeout=timeout)
    if not es:
        return []
    try:
        id_list = (es.get("esearchresult") or {}).get("idlist") or []
    except (AttributeError, TypeError):
        id_list = []
    if not id_list:
        return []
    ids = [str(x) for x in id_list[:cap] if x]
    if not ids:
        return []
    _throttle()
    sp = {"db": "pubmed", "retmode": "json", "id": ",".join(ids)}
    if api_key:
        sp["api_key"] = api_key
    sm_url = f"{_ESUMMARY}?{urllib.parse.urlencode(sp)}"
    sm = _http_get_json(sm_url, timeout=timeout)
    if not sm:
        return []
    out: list[dict[str, str]] = []
    try:
        result = (sm.get("result") or {})
        for pmid in ids:
            rec = result.get(pmid)
            if not isinstance(rec, dict):
                continue
            title = str(rec.get("title") or rec.get("sorttitle") or "")[:400]
            if not title:
                continue
            out.append(
                {
                    "pmid": str(pmid),
                    "title": title,
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "kind": "pubmed_article",
                }
            )
    except (TypeError, AttributeError):
        pass
    return out[:cap]
