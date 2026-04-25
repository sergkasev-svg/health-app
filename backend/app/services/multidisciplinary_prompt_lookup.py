from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PDF_PROMPT_FILE = _PROJECT_ROOT / "medical_knowledge" / "histamine" / "pdf_prompt_library.json"


def _load_json(path: Path, fallback: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return fallback


@lru_cache(maxsize=1)
def _load_library() -> dict[str, Any]:
    payload = _load_json(_PDF_PROMPT_FILE, {})
    return payload if isinstance(payload, dict) else {}


def _split_signals(value: str) -> list[str]:
    src = str(value or "").strip().lower()
    if not src:
        return []
    out = [src]
    out.extend([x.strip().lower() for x in re.split(r"[_\-/\s]+", src) if str(x).strip()])
    return [x for x in out if len(x) >= 4]


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


def build_multidisciplinary_context(user_text: str, document_text: str = "") -> dict[str, Any]:
    merged = " ".join([str(user_text or ""), str(document_text or "")]).strip().lower()
    lib = _load_library()
    docs = lib.get("documents") or []
    if not isinstance(docs, list):
        docs = []

    matched_docs: list[dict[str, Any]] = []
    hypotheses: list[str] = []
    questions: list[str] = []
    tests: list[str] = []
    specialist_routes: list[str] = []
    nutrition_focus: list[str] = []
    activity_focus: list[str] = []
    lenses: list[str] = []

    for row in docs:
        if not isinstance(row, dict):
            continue
        tags = [str(x).strip().lower() for x in (row.get("priority_tags") or []) if str(x).strip()]
        source = str(row.get("source_path") or "").strip()
        signals: list[str] = []
        for t in tags:
            signals.extend(_split_signals(t))
        for t in _split_signals(source):
            signals.append(t)
        if not signals:
            continue
        if not any(sig in merged for sig in signals):
            continue

        matched_docs.append(
            {
                "doc_id": str(row.get("doc_id") or "").strip(),
                "status": str(row.get("status") or "").strip(),
                "source_path": source,
                "priority_tags": tags[:8],
            }
        )
        hypotheses.extend([str(x).strip() for x in (row.get("diagnostic_hypotheses") or []) if str(x).strip()])
        questions.extend([str(x).strip() for x in (row.get("followup_questions") or []) if str(x).strip()])
        tests.extend([str(x).strip() for x in (row.get("recommended_tests") or []) if str(x).strip()])

        tag_blob = " ".join(tags)
        if any(k in tag_blob for k in ("nutrition", "sighi", "diet", "food_compatibility", "dao_support")):
            lenses.append("нутрициолог")
            nutrition_focus.append("Элиминация индивидуальных пищевых триггеров на 10-14 дней с дневником симптомов.")
        if any(k in tag_blob for k in ("biochemistry", "organic_acids", "metabolic", "mitochondria", "acidosis")):
            lenses.append("биохимик")
            nutrition_focus.append("Сверка нутритивных дефицитов и метаболического профиля по лабораторным данным.")
        if any(k in tag_blob for k in ("pots", "cfs", "long_covid", "dysautonomia", "inflammation_indices")):
            lenses.append("врач функциональной диагностики")
            activity_focus.append("Щадящая физическая активность с постепенным наращиванием, без постнагрузочного провала.")
        if any(k in tag_blob for k in ("mcas", "histamine", "allergy_signal", "mast_cell_stabilizers")):
            lenses.append("аллерголог-иммунолог")
            specialist_routes.append("Аллерголог-иммунолог")
        if any(k in tag_blob for k in ("thyroid", "endocrine", "hormone")):
            lenses.append("эндокринолог")
            specialist_routes.append("Эндокринолог")
        if any(k in tag_blob for k in ("gcms_microbiota", "dysbiosis", "gi")):
            specialist_routes.append("Гастроэнтеролог")

    links = lib.get("cross_document_links") or {}
    if isinstance(links, dict):
        route = str(links.get("doctor_route_target") or "").strip()
        if route:
            specialist_routes.append(route)

    return {
        "matched_docs": matched_docs[:12],
        "candidate_hypotheses": _dedup(hypotheses)[:8],
        "followup_questions": _dedup(questions)[:8],
        "recommended_tests": _dedup(tests)[:10],
        "specialist_routes": _dedup(specialist_routes)[:5],
        "nutrition_focus": _dedup(nutrition_focus)[:4],
        "activity_focus": _dedup(activity_focus)[:4],
        "expert_lenses": _dedup(lenses)[:6],
    }

