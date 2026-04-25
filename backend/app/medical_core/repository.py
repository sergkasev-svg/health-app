from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_CORE_ROOT = _PROJECT_ROOT / "medical_knowledge" / "medical_core"


def _tokens(text: str) -> list[str]:
    s = re.sub(r"[^\w\sа-яёa-z0-9-]", " ", (text or "").lower())
    return [w for w in s.split() if len(w) >= 3]


class MedicalCoreRepository:
    """Read-only repository for the add-only medical_core bundle."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or _CORE_ROOT

    @lru_cache(maxsize=1)
    def manifest(self) -> dict[str, Any]:
        path = self.root / "manifest.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    @lru_cache(maxsize=1)
    def catalog(self) -> list[dict[str, Any]]:
        path = self.root / "catalog_full_625.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [x for x in (data.get("items") or []) if isinstance(x, dict)]

    @lru_cache(maxsize=1)
    def search_index(self) -> list[dict[str, Any]]:
        path = self.root / "search_index.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [x for x in (data.get("items") or []) if isinstance(x, dict)]

    @lru_cache(maxsize=1)
    def complaint_links(self) -> dict[str, dict[str, Any]]:
        path = self.root / "complaint_disease_links.json"
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = [x for x in (data.get("items") or []) if isinstance(x, dict)]
        return {str(x.get("complaint_entry_id") or ""): x for x in rows if x.get("complaint_entry_id")}

    @lru_cache(maxsize=1)
    def behavior_rules(self) -> dict[str, Any]:
        path = self.root / "behavior_rules_competitor_aligned.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def by_entry_id(self) -> dict[str, dict[str, Any]]:
        return {str(x.get("entry_id") or ""): x for x in self.catalog() if x.get("entry_id")}

    def get(self, entry_id: str) -> dict[str, Any] | None:
        return self.by_entry_id().get(str(entry_id or ""))

    def search(self, query: str, *, types: set[str] | None = None, limit: int = 8) -> list[dict[str, Any]]:
        words = set(_tokens(query))
        if not words:
            return []
        index = self.search_index()
        scored: list[tuple[float, str]] = []
        for row in index:
            if types and str(row.get("type") or "") not in types:
                continue
            hay = " ".join([row.get("name") or "", row.get("category") or "", row.get("domain") or ""] + list(row.get("terms") or []))
            hay_words = set(_tokens(hay))
            overlap = len(words & hay_words)
            if overlap <= 0:
                continue
            score = float(overlap)
            if any(w in (row.get("name") or "").lower() for w in words):
                score += 1.5
            scored.append((score, str(row.get("entry_id") or "")))
        scored.sort(key=lambda x: x[0], reverse=True)
        by_id = self.by_entry_id()
        return [by_id[eid] for _, eid in scored[: max(1, limit)] if eid in by_id]
