"""
Извлечение и нормализация лабораторных значений из текста.
Производит список LabValue с каноническими кодами.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.apob_lab_context import (
    APOA1_REF_HIGH_G_L,
    APOA1_REF_LOW_G_L,
    APOB_REF_HIGH_G_L,
    APOB_REF_LOW_G_L,
    extract_apoa1_value_and_refs_g_l,
    extract_apob_g_per_l,
    extract_apob_reference_range_g_l,
)
from app.services.clinical_engine.contracts import LabValue
from app.services.clinical_engine.normalizer import normalize_marker_name

# Паттерны: (canonical_code, label, regex list for value, (ref_low, ref_high) optional)
# Значение берём из первой группы, референсы — при наличии
_BLOOD_BIOCHEM_PATTERNS: List[Dict[str, Any]] = [
    {
        "code": "total_cholesterol",
        "label": "Общий холестерин",
        "patterns": [
            r"общий\s+холестерин[:\s]+(\d+[,.]?\d*)",
            r"холестерин\s+общий[:\s]+(\d+[,.]?\d*)",
            r"total\s+cholesterol[:\s]+(\d+[,.]?\d*)",
            r"холестерин\s+[^\d]*(\d+[,.]?\d*)\s*(?:ммоль|mmol)",
        ],
        "unit": "ммоль/л",
        "ref": (3.5, 6.2),
    },
    {
        "code": "ldl_cholesterol",
        "label": "ЛПНП",
        # Не использовать «лпнп\s+[^\d]*(\d+)» — захватывает «< 3,00» вместо результата; ЛПНП даёт parse_lipid_values
        "patterns": [
            r"лпнп[:\s]+(\d+[,.]?\d*)\s*(?:ммоль|mmol|ммол)",
            r"ldl[:\s]+(\d+[,.]?\d*)\s*(?:ммоль|mmol|ммол)",
            r"холестерин\s*[-–]?\s*лпнп\D{0,20}(\d+[,.]?\d*)\s*(?:ммоль|mmol|ммол)",
            r"лпнп[:\s]+(\d+[,.]?\d*)",
            r"ldl[:\s]+(\d+[,.]?\d*)",
            r"холестерин\s+лпнп[:\s]+(\d+[,.]?\d*)",
        ],
        "unit": "ммоль/л",
        "ref": (0, 3.0),
    },
    {
        "code": "hdl_cholesterol",
        "label": "ЛПВП",
        "patterns": [
            r"лпвп[:\s]+(\d+[,.]?\d*)",
            r"hdl[:\s]+(\d+[,.]?\d*)",
            r"лпвп\s+[^\d]*(\d+[,.]?\d*)",
            r"hdl\s+[^\d]*(\d+[,.]?\d*)",
        ],
        "unit": "ммоль/л",
        "ref": (1.0, None),
    },
    {
        "code": "triglycerides",
        "label": "Триглицериды",
        "patterns": [
            r"триглицерид[ы]?[:\s]+(\d+[,.]?\d*)",
            r"тг[:\s]+(\d+[,.]?\d*)",
            r"триглицерид[ы]?\s+[^\d]*(\d+[,.]?\d*)",
        ],
        "unit": "ммоль/л",
        "ref": (0, 1.7),
    },
    {
        "code": "hba1c",
        "label": "HbA1c",
        "patterns": [
            r"hba1c[:\s]+(\d+[,.]?\d*)",
            r"гликированный\s+гемоглобин[:\s]+(\d+[,.]?\d*)",
            r"гликозилированный\s+гемоглобин[:\s]+(\d+[,.]?\d*)",
            r"hba1c\s+[^\d]*(\d+[,.]?\d*)\s*%",
        ],
        "unit": "%",
        "ref": (4.0, 6.0),
    },
    {
        "code": "fructosamine",
        "label": "Фруктозамин",
        "patterns": [
            r"фруктозамин[:\s]+(\d+[,.]?\d*)",
            r"фруктозамин\s+[^\d]*(\d+[,.]?\d*)",
        ],
        "unit": "мкмоль/л",
        "ref": (205, 285),
    },
    {
        "code": "homocysteine",
        "label": "Гомоцистеин",
        "patterns": [
            r"гомоцистеин[:\s]+(\d+[,.]?\d*)",
            r"гомоцистеин\s+[^\d]*(\d+[,.]?\d*)",
        ],
        "unit": "мкмоль/л",
        "ref": (5, 15),
    },
    {
        "code": "hs_crp",
        "label": "С-реактивный белок (высокочувствительный)",
        "patterns": [
            r"с-реактивный\s+белок[,\s]+высокочувствительный[:\s]+(\d+[,.]?\d*)",
            r"hs-crp[:\s]+(\d+[,.]?\d*)",
            r"hs\s*crp[:\s]+(\d+[,.]?\d*)",
            r"высокочувствительный\s+с-реактивный[:\s]+(\d+[,.]?\d*)",
        ],
        "unit": "мг/л",
        "ref": (0, 1.0),
    },
    {
        "code": "crp",
        "label": "С-реактивный белок",
        "patterns": [
            r"с-реактивный\s+белок[:\s]+(\d+[,.]?\d*)",
            r"crp[:\s]+(\d+[,.]?\d*)",
        ],
        "unit": "мг/л",
        "ref": (0, 5.0),
    },
    {
        "code": "lp_a",
        "label": "Липопротеин (а)",
        "patterns": [
            r"липопротеин\s*\(?\s*а\s*\)?[:\s]+(\d+[,.]?\d*)",
            r"лп\s*\(\s*а\s*\)[:\s]+(\d+[,.]?\d*)",
            r"lp\s*\(\s*a\s*\)[:\s]+(\d+[,.]?\d*)",
        ],
        "unit": "мг/дл",
        "ref": (0, 30),
    },
    {
        "code": "apo_a1",
        "label": "Аполипопротеин A1",
        "patterns": [
            r"аполипопротеин\s+а\s*1[:\s]+(\d+[,.]?\d*)",
            r"аполипопротеин\s+a\s*1[:\s]+(\d+[,.]?\d*)",
            r"аполипопротеин\s+а1[:\s]+(\d+[,.]?\d*)",
            r"апо\s*а\s*1[:\s]+(\d+[,.]?\d*)",
            r"apo\s*a\s*1[:\s]+(\d+[,.]?\d*)",
            r"apo\s*a1[:\s]+(\d+[,.]?\d*)",
        ],
        "unit": "г/л",
        "ref": (APOA1_REF_LOW_G_L, APOA1_REF_HIGH_G_L),
    },
    {
        "code": "apo_b",
        "label": "Аполипопротеин B",
        "patterns": [
            r"аполипопротеин\s+[вb][:\s]+(\d+[,.]?\d*)",
            r"апо\s*[вb][:\s]+(\d+[,.]?\d*)",
            r"apo\s*[bв][:\s]+(\d+[,.]?\d*)",
            r"apob[:\s]+(\d+[,.]?\d*)",
        ],
        "unit": "г/л",
        "ref": (0.6, 1.3),
    },
]


def _to_float(s: str) -> Optional[float]:
    try:
        return float(str(s).replace(",", ".").strip())
    except (ValueError, TypeError):
        return None


def _status_from_ref(value: float, ref_low: Optional[float], ref_high: Optional[float]) -> str:
    if ref_high is not None and value > ref_high:
        return "high"
    if ref_low is not None and value < ref_low:
        return "low"
    return "normal"


def _lipid_panel_dict_to_lab_values(lip: dict) -> List[LabValue]:
    """Словарь parse_lipid_values → LabValue (устойчивее regex «лпнп … < 3»)."""
    out: List[LabValue] = []
    mapping = [
        ("total_cholesterol", "total_cholesterol", "Общий холестерин", (3.5, 6.2)),
        ("ldl", "ldl_cholesterol", "ЛПНП", (0.0, 3.0)),
        ("hdl", "hdl_cholesterol", "ЛПВП", (1.0, None)),
        ("triglycerides", "triglycerides", "Триглицериды", (0.0, 1.7)),
    ]
    for lip_key, code, label, ref in mapping:
        val = lip.get(lip_key)
        if val is None:
            continue
        ref_low, ref_high = ref[0], ref[1] if len(ref) > 1 else None
        out.append(
            LabValue(
                code=code,
                label=label,
                value=val,
                value_text=str(val),
                unit="ммоль/л",
                ref_low=ref_low,
                ref_high=ref_high,
                ref_text=f"{ref_low}–{ref_high}" if ref_high is not None else None,
                status=_status_from_ref(val, ref_low, ref_high),
                source_text=None,
            )
        )
    return out


def extract_blood_biochemistry(text: str) -> List[LabValue]:
    """
    Извлекает биохимические показатели из текста.
    Два прохода по липидам (parse_lipid_values + нормализованная копия) снижает риск пропуска/ошибки OCR.
    Возвращает список LabValue с каноническими кодами.
    """
    if not text:
        return []
    low = text.lower()
    result: List[LabValue] = []
    seen: set[str] = set()

    # --- Липиды: приоритет устойчивому парсеру (не путает «< 3,00» с результатом ЛПНП)
    try:
        from app.services.lipid_engine import parse_lipid_values

        lip_merged: dict = {}
        variants = [
            text,
            text.replace("\u00a0", " ")
            .replace("\u2013", "-")
            .replace("\u2011", "-")
            .replace(";", ","),
        ]
        for variant in variants:
            part = parse_lipid_values(variant)
            for k, v in part.items():
                if v is not None and lip_merged.get(k) is None:
                    lip_merged[k] = v
        for lv in _lipid_panel_dict_to_lab_values(lip_merged):
            seen.add(lv.code)
            result.append(lv)
    except Exception:
        pass

    # Единый разбор апоВ по всему тексту (табличные и многострочные бланки РФ)
    apob_v = extract_apob_g_per_l(text)
    if apob_v is not None:
        seen.add("apo_b")
        rl, rh = extract_apob_reference_range_g_l(text)
        if rl is None or rh is None:
            rl, rh = APOB_REF_LOW_G_L, APOB_REF_HIGH_G_L
        result.append(
            LabValue(
                code="apo_b",
                label="Аполипопротеин B",
                value=apob_v,
                value_text=str(apob_v),
                unit="г/л",
                ref_low=rl,
                ref_high=rh,
                ref_text=f"{rl}–{rh}",
                status=_status_from_ref(apob_v, rl, rh),
                source_text=None,
            )
        )

    # Аполипопротеин A1: полная строка бланка (значение + референс)
    av, arl, arh = extract_apoa1_value_and_refs_g_l(text)
    if av is not None:
        seen.add("apo_a1")
        if arl is None or arh is None:
            arl, arh = APOA1_REF_LOW_G_L, APOA1_REF_HIGH_G_L
        result.append(
            LabValue(
                code="apo_a1",
                label="Аполипопротеин A1",
                value=av,
                value_text=str(av),
                unit="г/л",
                ref_low=arl,
                ref_high=arh,
                ref_text=f"{arl}–{arh}",
                status=_status_from_ref(av, arl, arh),
                source_text=None,
            )
        )

    for spec in _BLOOD_BIOCHEM_PATTERNS:
        code = spec["code"]
        if code in seen:
            continue
        if code == "apo_b":
            continue
        ref = spec.get("ref")
        ref_low = ref[0] if ref else None
        ref_high = ref[1] if ref and len(ref) > 1 else None
        value_num = None
        for pattern in spec["patterns"]:
            m = re.search(pattern, low, re.IGNORECASE)
            if m:
                value_num = _to_float(m.group(1))
                if value_num is not None:
                    break
        # Не подставлять верхнюю границу референса вместо результата (баг HbA1c 6.0 вместо 5.1)
        if code == "hba1c" and value_num is not None and ref_high is not None and abs(value_num - ref_high) < 0.01:
            value_num = None
        if value_num is None:
            continue
        seen.add(code)
        status = _status_from_ref(value_num, ref_low, ref_high)
        result.append(
            LabValue(
                code=code,
                label=spec["label"],
                value=value_num,
                value_text=str(value_num),
                unit=spec.get("unit"),
                ref_low=ref_low,
                ref_high=ref_high,
                ref_text=f"{ref_low}–{ref_high}" if ref_low is not None and ref_high is not None else None,
                status=status,
                source_text=None,
            )
        )
    return result


def count_numeric_values_with_refs(text: str) -> int:
    """Подсчёт валидных числовых показателей (признак «есть данные» для запрета fallback)."""
    return len(extract_blood_biochemistry(text))
