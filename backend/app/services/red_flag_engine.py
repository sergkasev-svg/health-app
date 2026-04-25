from __future__ import annotations

from typing import Any


RED_FLAGS: dict[str, dict[str, str]] = {
    "cannot_bear_weight": {"severity": "urgent", "message": "невозможно нормально наступать на ногу после травмы"},
    "gross_deformity": {"severity": "emergency", "message": "деформация конечности"},
    "hot_swollen_joint_with_fever": {"severity": "urgent", "message": "горячий отечный сустав с температурой"},
}

# Simple key -> message for stage1 pipeline
ORAL_RED_FLAGS_SIMPLE: dict[str, str] = {
    "facial_swelling": "отек лица на фоне зубной боли",
    "trouble_swallowing": "трудно глотать",
    "fever_with_dental_pain": "температура при зубной боли",
}

ORAL_RED_FLAGS: dict[str, dict[str, str]] = {
    "facial_swelling": {"severity": "urgent", "message": "отёк лица на фоне боли в зубе или десне"},
    "trouble_swallowing": {"severity": "urgent", "message": "затруднение глотания"},
    "trismus_like": {"severity": "urgent", "message": "трудно открыть рот"},
    "fever_with_dental_pain": {"severity": "urgent", "message": "температура на фоне выраженной зубной боли"},
    "rapid_spreading_swelling": {"severity": "urgent", "message": "быстро нарастающий отёк десны/щеки"},
    "persistent_bleeding_after_extraction": {
        "severity": "urgent",
        "message": "кровотечение после удаления зуба, которое не останавливается",
    },
}

ALL_RED_FLAGS: dict[str, dict[str, str]] = {**RED_FLAGS, **ORAL_RED_FLAGS}


def detect_red_flags(evidence_present: list[str] | set[str]) -> list[dict[str, Any]]:
    present = set(evidence_present or [])
    hits: list[dict[str, Any]] = []
    for key, meta in ALL_RED_FLAGS.items():
        if key in present:
            hits.append({"key": key, "severity": meta["severity"], "message": meta["message"]})
    return hits


def detect_red_flag_keys(evidence: list[str]) -> list[str]:
    """Return list of red-flag keys present in evidence (for stage1 pipeline)."""
    flags = []
    for k in evidence or []:
        if k in ALL_RED_FLAGS or k in ORAL_RED_FLAGS_SIMPLE:
            flags.append(k)
    return flags


# Текстовый поиск красных флагов по сырому вводу (V4 clinical reasoning)
RED_FLAGS_TEXT: list[str] = [
    "потеря сознания",
    "сильная боль в груди",
    "кровь в моче",
    "температура 39",
    "не могу дышать",
    "онемение",
    "слабость в руке",
    "деформация",
]


def detect_red_flags_from_text(text: str) -> list[str]:
    """Сканирует текст на наличие фраз-красных флагов. Возвращает список найденных фраз."""
    if not text:
        return []
    t = (text or "").lower().replace("ё", "е")
    found: list[str] = []
    for r in RED_FLAGS_TEXT:
        if (r or "").strip() and r in t:
            found.append(r)
    return list(dict.fromkeys(found))

