"""
Единые русские подписи показателей ОАК для отчётов (врач/пациент) и ключ дедупликации строк.
Исключает дубли «Hb» + «Гемоглобин» в одной таблице; латиница только там, где нет устойчивого русского ярлыка.
"""
from __future__ import annotations

import re
from typing import Any, Dict

# Канонический код (как в lab_value_extractor / LabValue.marker) → подпись для UI
CBC_CODE_TO_LABEL_RU: Dict[str, str] = {
    "Hb": "Гемоглобин",
    "Hct": "Гематокрит",
    "RBC": "Эритроциты",
    "MCV": "Средний объём эритроцитов (MCV)",
    "MCH": "Среднее содержание гемоглобина в эритроците (MCH)",
    "MCHC": "Средняя концентрация гемоглобина в эритроците (MCHC)",
    "RDW": "Ширина распределения эритроцитов по объёму (RDW)",
    "WBC": "Лейкоциты",
    "PLT": "Тромбоциты",
    "ESR": "СОЭ",
    "Reticulocytes": "Ретикулоциты",
    "Reticulocytes_rel": "Ретикулоциты",
    "Reticulocytes_abs": "Ретикулоциты (абс.)",
    "Neutrophils": "Нейтрофилы",
    "Lymphocytes": "Лимфоциты",
    "Monocytes": "Моноциты",
    "Eosinophils": "Эозинофилы",
    "Basophils": "Базофилы",
    "Neutrophils_abs": "Нейтрофилы (абс.)",
    "Lymphocytes_abs": "Лимфоциты (абс.)",
    "Monocytes_abs": "Моноциты (абс.)",
    "Segmented_neutrophils": "Нейтрофилы сегментоядерные",
    "Band_neutrophils": "Нейтрофилы палочкоядерные",
    "MPV": "Средний объём тромбоцитов (MPV)",
    "PDW": "Ширина распределения тромбоцитов по объёму (PDW)",
    "P-LCR": "Доля крупных тромбоцитов (P-LCR)",
}


def _norm_code(code: str) -> str:
    return (code or "").strip().lower().replace("-", "_")


def _looks_like_cbc_english_code(s: str) -> bool:
    """Только латиница (Hb, MPV, P-LCR …), не русские подписи."""
    s = (s or "").strip()
    if not s or len(s) > 22:
        return False
    if any("\u0400" <= ch <= "\u04ff" for ch in s):
        return False
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9+/_#-]*$", s))


def _build_reverse_label_map() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for code, ru in CBC_CODE_TO_LABEL_RU.items():
        nk = _norm_code(code)
        out[ru.lower()] = nk
        base = ru.split("(")[0].strip().lower()
        if base and len(base) > 2 and base not in out:
            out[base] = nk
    # Частые короткие формы на бланках
    out["гемоглобин"] = "hb"
    out["гематокрит"] = "hct"
    out["лейкоциты"] = "wbc"
    out["тромбоциты"] = "plt"
    out["эритроциты"] = "rbc"
    out["соэ"] = "esr"
    return out


_REVERSE_LABEL_MAP = _build_reverse_label_map()


def cbc_label_ru(code: str) -> str:
    """Подпись показателя для отчёта; при неизвестном коде возвращает код как есть."""
    c = (code or "").strip()
    if not c:
        return ""
    return CBC_CODE_TO_LABEL_RU.get(c, c)


def cbc_abnormal_row_dedup_key(row: Dict[str, Any]) -> str:
    """
    Один ключ на один показатель (Hb / Гемоглобин / «Гемоглобин …» → hb).
    """
    mc = str(row.get("marker_code") or "").strip()
    if mc:
        return _norm_code(mc)
    m = str(row.get("marker") or row.get("name") or "").strip()
    if _looks_like_cbc_english_code(m) and len(m) <= 22:
        return _norm_code(m)
    ml = m.lower()
    if ml in _REVERSE_LABEL_MAP:
        return _REVERSE_LABEL_MAP[ml]
    paren = re.search(r"\(([a-z0-9+\\-]{2,12})\)\s*$", ml, re.I)
    if paren:
        inner = paren.group(1).lower()
        if inner in ("mpv", "pdw", "mcv", "mch", "rdw", "mchc"):
            return inner.replace("-", "_")
    return ml[:80]


def cbc_group_markers_ru(codes: list[str]) -> str:
    """Строка маркеров для групповой интерпретации — по возможности на русском."""
    parts = []
    for c in codes:
        parts.append(cbc_label_ru(c))
    return ", ".join(p for p in parts if p)
