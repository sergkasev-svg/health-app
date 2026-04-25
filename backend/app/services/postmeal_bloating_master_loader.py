from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MASTER_FILE = _PROJECT_ROOT / "app" / "knowledge" / "postmeal_bloating_diarrhea_master.json"


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
def load_postmeal_bloating_master() -> dict[str, Any]:
    payload = _load_json(_MASTER_FILE, {})
    return payload if isinstance(payload, dict) else {}


def _causes_index() -> dict[str, dict[str, Any]]:
    causes = load_postmeal_bloating_master().get("causes")
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(causes, list):
        return out
    for row in causes:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "").strip()
        if cid:
            out[cid] = row
    return out


def _default_order() -> list[str]:
    policy = load_postmeal_bloating_master().get("core_reasoning_policy")
    if not isinstance(policy, dict):
        return []
    rows = policy.get("default_priority_order")
    return [str(x).strip() for x in (rows or []) if str(x).strip()] if isinstance(rows, list) else []


def red_flags() -> list[str]:
    rows = load_postmeal_bloating_master().get("red_flags")
    return [str(x).strip() for x in (rows or []) if str(x).strip()] if isinstance(rows, list) else []


def prioritize_causes(message: str, limit: int = 5) -> list[dict[str, Any]]:
    causes = _causes_index()
    order = _default_order()
    if not causes or not order:
        return []
    t = _norm(message)
    scored: list[tuple[float, int, str]] = []
    for idx, cid in enumerate(order):
        c = causes.get(cid) or {}
        title = str(c.get("title") or "").strip()
        if not title:
            continue
        score = max(0.0, float(len(order) - idx))
        if cid == "lactose_or_dairy_pattern" and any(x in t for x in ("молок", "творог", "сливк", "йогурт", "кефир", "сыр")):
            score += 5.5
        if cid == "fodmap_fermentation_pattern" and any(x in t for x in ("лук", "чеснок", "боб", "мед", "мёд", "фрукт", "сок", "сорбит", "ксилит")):
            score += 5.2
        if cid == "food_triggered_ibs_pattern":
            has_ibs_pattern = any(x in t for x in ("повтор", "хронич", "дефекац", "стул", "запор", "диаре")) and any(
                x in t for x in ("боль", "живот")
            )
            if has_ibs_pattern:
                score += 2.2
            else:
                score -= 4.8
        if cid == "acute_infectious_gastroenteritis_pattern" and any(
            x in t for x in ("температур", "лихорад", "рвот", "контакт", "отрав", "инфекц")
        ):
            score += 4.5
        if cid == "alarm_non_functional_bowel_route" and any(
            x in t for x in ("кров", "черн", "чёрн", "обмор", "обезвож", "неукротим")
        ):
            score += 10.0
        scored.append((score, idx, cid))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [
        {"id": cid, "title": str((causes.get(cid) or {}).get("title") or "").strip()}
        for _, _, cid in scored[: max(1, int(limit or 1))]
    ]


def detect_red_flags(message: str) -> list[str]:
    t = _norm(message)
    checks: list[tuple[str, tuple[str, ...]]] = [
        ("кровь в стуле", ("кров", "стул")),
        ("чёрный стул", ("чёрн", "стул")),
        ("высокая температура или выраженная лихорадка", ("температур",)),
        ("сильная или нарастающая боль в животе", ("сильн", "живот")),
        ("неукротимая рвота", ("неукрот", "рвот")),
        ("обморок или выраженное предобморочное состояние", ("обмор",)),
        ("признаки обезвоживания", ("обезвож",)),
        ("редкое мочеиспускание", ("редко", "моче")),
        ("спутанность сознания", ("спутан", "созн")),
        ("симптомы не уменьшаются и явно ухудшаются", ("ухудш",)),
    ]
    found: list[str] = []
    for label, keys in checks:
        if all(k in t for k in keys):
            found.append(label)
    if "кров" in t and "стул" in t and "кровь в стуле" not in found:
        found.append("кровь в стуле")
    if ("черн" in t or "чёрн" in t) and "стул" in t and "чёрный стул" not in found:
        found.append("чёрный стул")
    if any(x in t for x in ("предобмор", "головокруж", "теряю сознание")) and "обморок или выраженное предобморочное состояние" not in found:
        found.append("обморок или выраженное предобморочное состояние")
    dedup: list[str] = []
    seen: set[str] = set()
    for row in found:
        key = row.lower()
        if key in seen:
            continue
        seen.add(key)
        dedup.append(row)
    return dedup[:8]


def single_mild_message() -> str:
    tl = load_postmeal_bloating_master().get("tests_logic")
    if not isinstance(tl, dict):
        return "При единичном лёгком эпизоде срочные анализы обычно не нужны."
    row = tl.get("single_mild_episode")
    if not isinstance(row, dict):
        return "При единичном лёгком эпизоде срочные анализы обычно не нужны."
    return str(row.get("message") or "").strip() or "При единичном лёгком эпизоде срочные анализы обычно не нужны."

