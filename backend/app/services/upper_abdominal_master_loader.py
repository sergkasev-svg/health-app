from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MASTER_FILE = _PROJECT_ROOT / "app" / "knowledge" / "upper_abdominal_pain_master.json"


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
def load_upper_abdominal_master() -> dict[str, Any]:
    payload = _load_json(_MASTER_FILE, {})
    return payload if isinstance(payload, dict) else {}


def upper_abdominal_reasoning_order() -> list[str]:
    cfg = load_upper_abdominal_master()
    policy = cfg.get("core_reasoning_policy") if isinstance(cfg.get("core_reasoning_policy"), dict) else {}
    order = policy.get("default_priority_order") if isinstance(policy.get("default_priority_order"), list) else []
    return [str(x).strip() for x in order if str(x).strip()]


def upper_abdominal_red_flags() -> list[str]:
    cfg = load_upper_abdominal_master()
    rows = cfg.get("red_flags") if isinstance(cfg.get("red_flags"), list) else []
    return [str(x).strip() for x in rows if str(x).strip()]


def _causes_index() -> dict[str, dict[str, Any]]:
    causes = load_upper_abdominal_master().get("causes")
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


def _routing_buckets() -> dict[str, list[str]]:
    cfg = load_upper_abdominal_master()
    routing = cfg.get("routing_logic") if isinstance(cfg.get("routing_logic"), dict) else {}
    trig = routing.get("if_trigger_contains") if isinstance(routing.get("if_trigger_contains"), dict) else {}
    out: dict[str, list[str]] = {}
    for key, rows in trig.items():
        if isinstance(rows, list):
            out[key] = [str(x).strip() for x in rows if str(x).strip()]
    return out


def _trigger_bucket(message: str) -> str:
    t = _norm(message)
    if any(x in t for x in ("нпвп", "ибупроф", "диклоф", "кеторол", "алког", "вино", "пиво")):
        return "alcohol_or_nsaids"
    if any(x in t for x in ("много", "переел", "большой объем", "обильн")):
        return "large_meal"
    return "fatty_or_fried_meal"


def prioritize_upper_abdominal_causes(message: str, limit: int = 5) -> list[dict[str, Any]]:
    order = upper_abdominal_reasoning_order()
    causes = _causes_index()
    if not order or not causes:
        return []
    routed = _routing_buckets().get(_trigger_bucket(message), [])
    t = _norm(message)

    scored: list[tuple[float, int, str]] = []
    for idx, cid in enumerate(order):
        cause = causes.get(cid) or {}
        title = str(cause.get("title") or "").strip()
        if not title:
            continue
        score = max(0.0, float(len(order) - idx))
        if cid in routed:
            score += 6.5
        if cid == "biliary_pattern" and any(x in t for x in ("прав", "подреб", "справа")):
            score += 4.0
        if cid == "reflux_or_postprandial_reflux" and any(x in t for x in ("изжог", "кисл", "жжен", "лежа", "лёжа")):
            score += 4.0
        if cid == "pancreatic_warning_pattern" and any(x in t for x in ("сильн", "нараста", "в спину", "рвот", "температур")):
            score += 3.5
        if cid == "ibs_not_primary_for_upper_abdomen" and not any(x in t for x in ("стул", "дефекац", "диаре", "запор")):
            score -= 5.0
        scored.append((score, idx, cid))

    scored.sort(key=lambda x: (-x[0], x[1]))
    out: list[dict[str, Any]] = []
    for _, _, cid in scored[: max(1, int(limit or 1))]:
        row = causes.get(cid) or {}
        out.append({"id": cid, "title": str(row.get("title") or "").strip()})
    return out


def detect_upper_abdominal_red_flags(message: str) -> list[str]:
    t = _norm(message)
    patterns: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
        ("сильная или нарастающая боль в верхней части живота", ("сильн", "верхн"), ("нараста", "эпигастр", "живот")),
        ("сильная боль справа под рёбрами", ("сильн",), ("справа", "подреб")),
        ("боль, отдающая в спину", tuple(), ("в спину", "отда", "ирради")),
        ("многократная рвота", ("рвот",), ("многократ",)),
        ("температура или озноб", tuple(), ("температур", "озноб")),
        ("чёрный стул", ("стул",), ("черн", "чёрн", "мелена")),
        ("кровь в рвоте", ("рвот",), ("кров",)),
        ("рвота типа кофейной гущи", tuple(), ("кофейн", "гущ")),
        ("обморок или выраженное головокружение", tuple(), ("обмор", "предобмор", "головокруж")),
        ("одышка", tuple(), ("одыш", "тяжело дыш")),
        ("боль в груди", tuple(), ("боль в груди", "за грудин")),
        ("желтуха", tuple(), ("желтух", "пожелт", "желтые глаза", "жёлтые глаза")),
        ("невозможность пить жидкость", tuple(), ("не могу пить", "не удается пить", "не удаётся пить")),
        ("резкое ухудшение общего состояния", tuple(), ("резко хуже", "резкое ухудш", "очень плохо")),
    ]
    found: list[str] = []
    for label, must, any_of in patterns:
        if must and not all(k in t for k in must):
            continue
        if any(k in t for k in any_of):
            found.append(label)
    dedup: list[str] = []
    seen: set[str] = set()
    for row in found:
        key = row.lower()
        if key in seen:
            continue
        seen.add(key)
        dedup.append(row)
    return dedup[:8]


def single_episode_message() -> str:
    tl = load_upper_abdominal_master().get("tests_logic")
    if not isinstance(tl, dict):
        return "Если это единичный лёгкий эпизод и симптомы проходят, срочные анализы обычно не нужны."
    row = tl.get("single_mild_episode_after_food")
    if not isinstance(row, dict):
        return "Если это единичный лёгкий эпизод и симптомы проходят, срочные анализы обычно не нужны."
    msg = str(row.get("message") or "").strip()
    return msg or "Если это единичный лёгкий эпизод и симптомы проходят, срочные анализы обычно не нужны."


def recurrent_fatty_or_ruq_tests() -> list[str]:
    tl = load_upper_abdominal_master().get("tests_logic")
    if not isinstance(tl, dict):
        return []
    row = tl.get("recurrent_fatty_food_or_right_upper_abdomen_pattern")
    tests = row.get("recommend_tests") if isinstance(row, dict) else []
    return [str(x).strip() for x in (tests or []) if str(x).strip()]

