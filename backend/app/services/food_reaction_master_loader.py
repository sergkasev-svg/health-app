from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MASTER_FILE = _PROJECT_ROOT / "app" / "knowledge" / "food_reaction_master.json"
_LEGACY_MASTER_FILE = _PROJECT_ROOT / "app" / "knowledge" / "food_reaction_headache_nausea.json"


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
def load_food_reaction_master() -> dict[str, Any]:
    payload = _load_json(_MASTER_FILE, {})
    if not payload:
        payload = _load_json(_LEGACY_MASTER_FILE, {})
    return payload if isinstance(payload, dict) else {}


def master_reasoning_order() -> list[str]:
    cfg = load_food_reaction_master()
    policy = cfg.get("core_reasoning_policy") if isinstance(cfg.get("core_reasoning_policy"), dict) else {}
    order = policy.get("default_priority_order") if isinstance(policy.get("default_priority_order"), list) else []
    return [str(x).strip() for x in order if str(x).strip()]


def master_red_flags() -> list[str]:
    cfg = load_food_reaction_master()
    rf = cfg.get("red_flags") if isinstance(cfg.get("red_flags"), list) else []
    return [str(x).strip() for x in rf if str(x).strip()]


def _causes_index() -> dict[str, dict[str, Any]]:
    causes = load_food_reaction_master().get("causes")
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(causes, list):
        return out
    for row in causes:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "").strip()
        if not cid:
            continue
        out[cid] = row
    return out


def _routing_lists() -> dict[str, list[str]]:
    cfg = load_food_reaction_master()
    routing = cfg.get("routing_logic") if isinstance(cfg.get("routing_logic"), dict) else {}
    triggers = routing.get("if_trigger_contains") if isinstance(routing.get("if_trigger_contains"), dict) else {}
    return {
        key: [str(x).strip() for x in value if str(x).strip()]
        for key, value in triggers.items()
        if isinstance(value, list)
    }


def _trigger_bucket(message: str) -> str:
    t = _norm(message)
    if any(x in t for x in ("вино", "сыр", "копчен", "копчён", "копч", "фермент", "выдержан")):
        return "wine_cheese_smoked_fermented"
    if any(x in t for x in ("молок", "творог", "йогурт", "кефир", "сливк")):
        return "dairy"
    if any(x in t for x in ("сладк", "десерт", "торт", "шоколад", "пирож")):
        return "sweet_or_dessert"
    return "fatty_or_fried_food"


def prioritize_food_causes(message: str, limit: int = 5) -> list[dict[str, Any]]:
    order = master_reasoning_order()
    causes = _causes_index()
    if not order or not causes:
        return []

    routing = _routing_lists()
    bucket = _trigger_bucket(message)
    routed = routing.get(bucket, [])

    weighted: list[tuple[float, int, str]] = []
    msg = _norm(message)
    for idx, cid in enumerate(order):
        cause = causes.get(cid) or {}
        title = str(cause.get("title") or "").strip()
        if not title:
            continue
        score = max(0.0, float(len(order) - idx))
        if cid in routed:
            score += 7.5
        for trigger in (cause.get("triggers") or []):
            tr = _norm(str(trigger or ""))
            if tr and tr in msg:
                score += 1.4
        for clue in (cause.get("supporting_clues") or []):
            cl = _norm(str(clue or ""))
            if cl and cl in msg:
                score += 1.0
        weighted.append((score, idx, cid))

    weighted.sort(key=lambda x: (-x[0], x[1]))
    out: list[dict[str, Any]] = []
    for _, _, cid in weighted[: max(1, int(limit or 1))]:
        c = causes.get(cid) or {}
        out.append(
            {
                "id": cid,
                "title": str(c.get("title") or "").strip(),
                "priority": str(c.get("priority") or "").strip(),
            }
        )
    return out


def is_histamine_pattern(message: str) -> bool:
    t = _norm(message)
    has_triggers = any(x in t for x in ("вино", "сыр", "копчен", "копчён", "копч", "фермент", "выдержан"))
    has_pattern = any(x in t for x in ("покраснен", "зуд", "сып", "залож", "сердц", "тахикард", "мигрен"))
    return has_triggers and has_pattern


def single_episode_tests_not_needed_message() -> str:
    cfg = load_food_reaction_master()
    tl = cfg.get("tests_logic") if isinstance(cfg.get("tests_logic"), dict) else {}
    single = tl.get("single_mild_episode") if isinstance(tl.get("single_mild_episode"), dict) else {}
    msg = str(single.get("message") or "").strip()
    return msg or "При единичном лёгком эпизоде без красных флагов анализы обычно не нужны."


def recurrent_food_tests() -> list[str]:
    cfg = load_food_reaction_master()
    tl = cfg.get("tests_logic") if isinstance(cfg.get("tests_logic"), dict) else {}
    rec = tl.get("recurrent_fatty_food_pattern") if isinstance(tl.get("recurrent_fatty_food_pattern"), dict) else {}
    tests = rec.get("recommend_tests") if isinstance(rec.get("recommend_tests"), list) else []
    return [str(x).strip() for x in tests if str(x).strip()]

