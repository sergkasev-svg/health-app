from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_DEFAULT_DIR = _PROJECT_ROOT / "backend" / "app" / "knowledge" / "scenario_packs"
_FALLBACK_DIR = _PROJECT_ROOT / "app" / "knowledge" / "scenario_packs"


@dataclass(slots=True)
class ScenarioPack:
    id: str
    category: str
    title_ru: str
    version: str
    chief_complaint_patterns: list[str]
    body_regions: list[str]
    must_ask: list[str]
    red_flags: list[str]
    likely_hypotheses: list[str]
    possible_tests: list[str]
    self_care: list[str]
    care_path: dict[str, Any]
    notes: str = ""
    source_path: str = ""
    raw: dict[str, Any] | None = None


def get_scenario_pack_root() -> Path:
    if _DEFAULT_DIR.exists():
        return _DEFAULT_DIR
    return _FALLBACK_DIR


def _normalize_pack(data: dict[str, Any], source_path: Path) -> ScenarioPack:
    cc_patterns = data.get("chief_complaint_patterns")
    if not cc_patterns and data.get("chief_complaint"):
        cc_patterns = [str(data.get("chief_complaint")).strip()]
    hypotheses = data.get("likely_hypotheses") or data.get("hypotheses") or []
    return ScenarioPack(
        id=str(data.get("id") or source_path.stem),
        category=str(data.get("category") or source_path.parent.name),
        title_ru=str(data.get("title_ru") or data.get("chief_complaint") or source_path.stem.replace("_", " ")),
        version=str(data.get("version") or "v1"),
        chief_complaint_patterns=[str(x).strip() for x in (cc_patterns or []) if str(x).strip()],
        body_regions=[str(x).strip() for x in (data.get("body_regions") or []) if str(x).strip()],
        must_ask=[str(x).strip() for x in (data.get("must_ask") or []) if str(x).strip()],
        red_flags=[str(x).strip() for x in (data.get("red_flags") or []) if str(x).strip()],
        likely_hypotheses=[str(x).strip() for x in hypotheses if str(x).strip()],
        possible_tests=[str(x).strip() for x in (data.get("possible_tests") or []) if str(x).strip()],
        self_care=[str(x).strip() for x in (data.get("self_care") or []) if str(x).strip()],
        care_path=data.get("care_path") if isinstance(data.get("care_path"), dict) else {},
        notes=str(data.get("notes") or "").strip(),
        source_path=str(source_path),
        raw=data,
    )


@lru_cache(maxsize=1)
def load_all_scenario_packs() -> list[ScenarioPack]:
    root = get_scenario_pack_root()
    out: list[ScenarioPack] = []
    if not root.exists():
        return out
    for fp in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        out.append(_normalize_pack(payload, fp))
    return out


@lru_cache(maxsize=1)
def load_manifest() -> list[dict[str, Any]]:
    root = get_scenario_pack_root()
    knowledge_dir = root.parent
    manifest_candidates = [
        knowledge_dir / "manifest.json",
        _PROJECT_ROOT / "manifest.json",
    ]
    for fp in manifest_candidates:
        if not fp.exists():
            continue
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            items = payload.get("items")
            if isinstance(items, list):
                return items
    return []


def get_scenario_pack_by_id(pack_id: str) -> ScenarioPack | None:
    pid = str(pack_id or "").strip().lower()
    if not pid:
        return None
    for pack in load_all_scenario_packs():
        if pack.id.lower() == pid:
            return pack
    return None


def list_scenario_categories() -> list[str]:
    return sorted({pack.category for pack in load_all_scenario_packs() if pack.category})
