"""
Dynamic complaint-based prioritization.
Builds auto-updated keyword and disease boosts from user complaints.
"""
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any


_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_USERS_ROOT = _BACKEND_DIR / "data" / "users"
_OUT_FILE = _BACKEND_DIR / "data" / "complaint_priority.json"
_TOP50_FILE = _PROJECT_ROOT / "medical_knowledge" / "ingestion" / "clinical_profile_overrides_top50.json"

_CACHE: dict[str, Any] | None = None
_TTL_SECONDS = 600  # auto-refresh every 10 minutes

_STOPWORDS = {
    "и", "в", "во", "на", "с", "со", "к", "по", "за", "от", "до", "у", "о", "об",
    "что", "как", "где", "когда", "почему", "мне", "меня", "мой", "моя", "мои",
    "это", "или", "но", "ли", "бы", "очень", "сильно", "просто", "нужно", "надо",
    "уже", "ещё", "еще", "есть", "был", "была", "были", "так", "для", "при",
    "this", "that", "with", "from", "have", "has", "was", "were", "the", "and",
}


def _tokenize(text: str) -> list[str]:
    s = re.sub(r"[^\w\sа-яёa-z0-9]", " ", (text or "").lower())
    out = []
    for w in s.split():
        if len(w) < 3 or w in _STOPWORDS:
            continue
        out.append(w)
    return out


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _collect_complaint_texts() -> list[str]:
    texts: list[str] = []
    if not _USERS_ROOT.exists():
        return texts
    for user_dir in _USERS_ROOT.iterdir():
        if not user_dir.is_dir():
            continue
        symptoms = _load_json(user_dir / "symptoms.json").get("entries") or []
        for e in symptoms:
            if isinstance(e, dict) and e.get("text"):
                texts.append(str(e.get("text")))
        chat = _load_json(user_dir / "chat.json").get("messages") or []
        for m in chat:
            if not isinstance(m, dict):
                continue
            if (m.get("role") or "").strip().lower() != "user":
                continue
            content = str(m.get("content") or "").strip()
            if content:
                texts.append(content)
    return texts


def _load_top50_ids() -> set[int]:
    payload = _load_json(_TOP50_FILE)
    rules = payload.get("disease_rules") or []
    out = set()
    for r in rules:
        if not isinstance(r, dict):
            continue
        rid = r.get("id")
        if isinstance(rid, int):
            out.add(rid)
    return out


def _build_disease_boosts(profiles: list[dict[str, Any]], keyword_counts: Counter) -> dict[str, float]:
    if not profiles or not keyword_counts:
        return {}
    top = keyword_counts.most_common(80)
    top_words = [w for w, _ in top]
    out: dict[str, float] = {}
    for p in profiles:
        pid = p.get("id")
        if pid is None:
            continue
        hay = " ".join(
            [
                str(p.get("name") or "").lower(),
                str(p.get("description") or "").lower(),
                str(p.get("category") or "").lower(),
                " ".join((p.get("anamnesis") or [])),
                " ".join((p.get("diagnostics") or [])),
                " ".join((p.get("treatment") or [])),
                " ".join((p.get("medications_recommended") or [])),
            ]
        ).lower()
        hit_weight = 0.0
        for w, c in top[:40]:
            if w in hay:
                hit_weight += min(0.08 * c, 0.35)
        if hit_weight > 0:
            out[str(pid)] = round(min(hit_weight, 2.0), 3)
    return out


def rebuild_priority_index(profiles: list[dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
    global _CACHE
    now = time.time()
    if not force and _CACHE and (now - float(_CACHE.get("updated_at_ts") or 0)) < _TTL_SECONDS:
        return _CACHE

    texts = _collect_complaint_texts()
    counts = Counter()
    for t in texts:
        counts.update(_tokenize(t))

    top_keywords = counts.most_common(120)
    disease_boosts = _build_disease_boosts(profiles or [], counts)
    data = {
        "updated_at_ts": now,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "total_complaints": len(texts),
        "top_keywords": [{"word": w, "count": int(c)} for w, c in top_keywords],
        "disease_boosts": disease_boosts,
        "top50_ids": sorted(_load_top50_ids()),
    }
    _OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _OUT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _CACHE = data
    return data


def get_priority_context(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    return rebuild_priority_index(profiles=profiles, force=False)

