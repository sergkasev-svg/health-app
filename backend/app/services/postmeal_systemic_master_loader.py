from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MASTER_FILE = _PROJECT_ROOT / "app" / "knowledge" / "postmeal_nausea_weakness_headache_master.json"


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
def load_postmeal_systemic_master() -> dict[str, Any]:
    payload = _load_json(_MASTER_FILE, {})
    return payload if isinstance(payload, dict) else {}


def _default_order() -> list[str]:
    policy = load_postmeal_systemic_master().get("core_reasoning_policy")
    if not isinstance(policy, dict):
        return []
    order = policy.get("default_priority_order")
    return [str(x).strip() for x in (order or []) if str(x).strip()] if isinstance(order, list) else []


def _causes_index() -> dict[str, dict[str, Any]]:
    rows = load_postmeal_systemic_master().get("causes")
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "").strip()
        if cid:
            out[cid] = row
    return out


def red_flags() -> list[str]:
    rows = load_postmeal_systemic_master().get("red_flags")
    return [str(x).strip() for x in (rows or []) if str(x).strip()] if isinstance(rows, list) else []


def detect_red_flags(message: str) -> list[str]:
    t = _norm(message)
    checks: list[tuple[str, tuple[str, ...]]] = [
        ("обморок", ("обмор",)),
        ("сильное головокружение", ("сильн", "головокруж")),
        ("боль в груди", ("боль в груди",)),
        ("одышка", ("одыш",)),
        ("спутанность сознания", ("спутан", "созн")),
        ("сильная слабость", ("сильн", "слаб")),
        ("невозможность стоять", ("не могу стоять",)),
        ("резкое ухудшение состояния", ("резко хуже",)),
    ]
    out: list[str] = []
    for label, keys in checks:
        if all(k in t for k in keys):
            out.append(label)
    if any(x in t for x in ("не могу встать", "невозможно стоять")) and "невозможность стоять" not in out:
        out.append("невозможность стоять")
    if "обмор" in t and "обморок" not in out:
        out.append("обморок")
    if "боль в груди" in t and "боль в груди" not in out:
        out.append("боль в груди")
    if "одыш" in t and "одышка" not in out:
        out.append("одышка")
    return out[:8]


def prioritize_causes(message: str, limit: int = 5) -> list[dict[str, Any]]:
    order = _default_order()
    causes = _causes_index()
    if not order or not causes:
        return []
    t = _norm(message)
    scored: list[tuple[float, int, str]] = []
    for idx, cid in enumerate(order):
        row = causes.get(cid) or {}
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        score = max(0.0, float(len(order) - idx))
        if cid == "fatty_food_systemic_overload" and any(x in t for x in ("жирн", "жарен", "семеч", "орех", "фастфуд")):
            score += 5.0
        if cid == "postprandial_vascular_reaction" and any(x in t for x in ("слаб", "дурнот", "ватн", "сонлив", "головокруж")):
            score += 4.0
        if cid == "sugar_glucose_reaction" and any(x in t for x in ("сладк", "десерт", "шоколад", "сок", "сахар")):
            score += 5.0
        if cid == "histamine_conditional_pattern":
            has_hist_food = any(x in t for x in ("вино", "сыр", "копчен", "копчён", "копч"))
            has_hist_sym = any(x in t for x in ("покрасн", "сердц", "залож", "зуд"))
            if has_hist_food and has_hist_sym:
                score += 2.5
            else:
                score -= 4.5
        if cid == "alarm_systemic_route" and any(x in t for x in ("обмор", "одыш", "боль в груди", "спутан", "не могу стоять")):
            score += 10.0
        scored.append((score, idx, cid))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [
        {"id": cid, "title": str((causes.get(cid) or {}).get("title") or "").strip()}
        for _, _, cid in scored[: max(1, int(limit or 1))]
    ]


def recurrent_tests() -> list[str]:
    tl = load_postmeal_systemic_master().get("tests_logic")
    if not isinstance(tl, dict):
        return []
    rec = tl.get("recurrent_pattern")
    tests = rec.get("recommend_tests") if isinstance(rec, dict) else []
    return [str(x).strip() for x in (tests or []) if str(x).strip()]

