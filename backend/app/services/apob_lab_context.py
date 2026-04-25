"""
Аполипопротеин B (ApoB): извлечение из текста лабораторных бланков (RU/EN) и клинический контекст.

Используется в липидном профиле и смежных биохимических выписках — единая точка опроса по всему тексту.
Референсы ориентировочные; лаборатория и врач задают целевые значения индивидуально.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# г/л — ориентиры по частым референсам РФ-лабораторий; при наличии диапазона на бланке используем его
APOB_REF_LOW_G_L: float = 0.75
APOB_REF_HIGH_G_L: float = 1.50

# Аполипопротеин A1 (г/л) — если на бланке нет своего диапазона
APOA1_REF_LOW_G_L: float = 1.20
APOA1_REF_HIGH_G_L: float = 1.90


def _parse_float_loose(raw: str) -> Optional[float]:
    try:
        return float(str(raw).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def extract_apob_g_per_l(text: str) -> Optional[float]:
    """
    Извлекает апоВ в г/л. Игнорирует заведомо чужие масштабы; при сомнении — None.
    """
    if not text or not str(text).strip():
        return None
    low = str(text).lower().replace("\u00a0", " ")
    # Порядок: более специфичные шаблоны первыми
    patterns = [
        # «Аполипопротеин B 1.41 г/л»
        r"аполипопротеин\s*[Bbв]\s*(?:\([^)]{0,40}\))?\s*(\d+[,.]\d+|\d+)\s*(?:г/л|g/l|г\s*/\s*л)",
        r"аполипопротеин\s+в\s+(\d+[,.]\d+|\d+)\s*(?:г/л|g/l)",
        r"аполипопротеин\s+b\s+(\d+[,.]\d+|\d+)\s*(?:г/л|g/l)",
        # «апо в : 1.2», «apo b 1.2»
        r"апо\s*[Bbв]\s*[-–]?\s*100\s*[:\s]+(\d+[,.]\d+|\d+)",
        r"апо\s*[Bbв]\s*[:\s]+(\d+[,.]\d+|\d+)(?:\s*(?:г/л|g/l))?",
        r"apo\s*b\s*[:\s]+(\d+[,.]\d+|\d+)(?:\s*(?:г/л|g/l))?",
        r"apob\s*[:\s]+(\d+[,.]\d+|\d+)(?:\s*(?:г/л|g/l))?",
        # Табличная строка без единиц сразу после числа
        r"аполипопротеин\s*[Bbв]\s+(\d+[,.]\d+|\d+)\b(?!\s*мг)",
    ]
    for rx in patterns:
        m = re.search(rx, low, re.IGNORECASE)
        if not m:
            continue
        v = _parse_float_loose(m.group(1))
        if v is None:
            continue
        # г/л: обычно 0.35–2.5; выше — подозрение на мг/дл или ошибку OCR
        if 0.2 <= v <= 3.0:
            return v
        if 30.0 <= v <= 250.0:
            # иногда печатают мг/дл без подписи
            return round(v / 100.0, 3)
    return None


def extract_apob_reference_range_g_l(text: str) -> tuple[Optional[float], Optional[float]]:
    """
    Диапазон референса ApoB с той же строки, что и результат (например «1,41 г/л 0,75 - 1,50»).
    """
    if not text or not str(text).strip():
        return None, None
    for line in str(text).splitlines():
        low = line.lower().replace("\u00a0", " ")
        if not re.search(
            r"(?:аполипопротеин\s*[bв]\b|apob\b|apo\s*b\b)(?!\s*а1)",
            low,
            re.IGNORECASE,
        ):
            continue
        m = re.search(
            r"(?:г/л|g/l)\s+(\d+[,.]\d+|\d+)\s*[-–]\s*(\d+[,.]\d+|\d+)",
            low,
            re.IGNORECASE,
        )
        if not m:
            m = re.search(
                r"(\d+[,.]\d+|\d+)\s*[-–]\s*(\d+[,.]\d+|\d+)\s*(?:г/л|g/l)",
                low,
                re.IGNORECASE,
            )
        if m:
            lo, hi = _parse_float_loose(m.group(1)), _parse_float_loose(m.group(2))
            if lo is not None and hi is not None and 0.3 <= lo < hi <= 2.5:
                return lo, hi
    return None, None


def extract_apoa1_value_and_refs_g_l(text: str) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Значение ApoA1 и референс с строки бланка: «Аполипопротеин А1 2,00 г/л 1,20 - 1,90».
    Возвращает (value, ref_low, ref_high); ref_* могут быть None — тогда брать APOA1_REF_*.
    """
    if not text or not str(text).strip():
        return None, None, None
    for line in str(text).splitlines():
        low = line.lower().replace("\u00a0", " ")
        if not re.search(
            r"(?:аполипопротеин\s*а\s*1|аполипопротеин\s+a\s*1|апо\s*а\s*1|апо\s*a\s*1|apo\s*a\s*1|apo\s*a1)\b",
            low,
            re.IGNORECASE,
        ):
            continue
        # «Аполипопротеин А1 2,00 1,20 - 1,90 г/л» — без «г/л» сразу после результата
        m_triplet = re.search(
            r"(?:аполипопротеин\s*а\s*1|аполипопротеин\s+a\s*1|апо\s*а\s*1|апо\s*a\s*1|apo\s*a\s*1|apo\s*a1)\D{0,20}"
            r"(\d+[,.]\d+|\d+)\s+(\d+[,.]\d+|\d+)\s*[-–]\s*(\d+[,.]\d+|\d+)\s*(?:г/л|g/l)",
            low,
            re.IGNORECASE,
        )
        if m_triplet:
            v, lo, hi = (
                _parse_float_loose(m_triplet.group(1)),
                _parse_float_loose(m_triplet.group(2)),
                _parse_float_loose(m_triplet.group(3)),
            )
            if v is not None and 0.4 <= v <= 3.5 and lo is not None and hi is not None and 0.5 < lo < hi < 3.0:
                return v, lo, hi
        mfull = re.search(
            r"(?:аполипопротеин\s*а\s*1|аполипопротеин\s+a\s*1|апо\s*а\s*1|апо\s*a\s*1|apo\s*a\s*1|apo\s*a1)\D{0,40}?"
            r"(\d+[,.]\d+|\d+)\s*(?:г/л|g/l)\s+(\d+[,.]\d+|\d+)\s*[-–]\s*(\d+[,.]\d+|\d+)",
            low,
            re.IGNORECASE,
        )
        if mfull:
            v, lo, hi = (
                _parse_float_loose(mfull.group(1)),
                _parse_float_loose(mfull.group(2)),
                _parse_float_loose(mfull.group(3)),
            )
            if v is not None and 0.4 <= v <= 3.5:
                if lo is not None and hi is not None and 0.5 < lo < hi < 3.0:
                    return v, lo, hi
                return v, None, None
        mv = re.search(
            r"(?:аполипопротеин\s*а\s*1|аполипопротеин\s+a\s*1|апо\s*а\s*1|апо\s*a\s*1|apo\s*a\s*1|apo\s*a1)\D{0,40}?"
            r"(\d+[,.]\d+|\d+)\s*(?:г/л|g/l)",
            low,
            re.IGNORECASE,
        )
        if mv:
            v = _parse_float_loose(mv.group(1))
            if v is not None and 0.4 <= v <= 3.5:
                mr = re.search(
                    r"(\d+[,.]\d+|\d+)\s*[-–]\s*(\d+[,.]\d+|\d+)\s*(?:г/л|g/l)?",
                    low[mv.end() :],
                    re.IGNORECASE,
                )
                if mr:
                    lo, hi = _parse_float_loose(mr.group(1)), _parse_float_loose(mr.group(2))
                    if lo is not None and hi is not None and 0.5 < lo < hi < 3.0:
                        return v, lo, hi
                return v, None, None
    return None, None, None


def apob_marker_mentioned(text: str) -> bool:
    """В тексте есть явное упоминание апоВ (даже без извлечённого числа)."""
    if not text:
        return False
    low = text.lower().replace("\u00a0", " ")
    return bool(
        re.search(
            r"(?:аполипопротеин\s*[Bbв]|апо\s*[-–]?\s*b\b|апоб\b|apob\b|apo\s*b\b|"
            r"апо\s*в\b(?!\s*а1)|аполипопротеин\s+в\b)",
            low,
            re.IGNORECASE,
        )
    )


def atherogenic_lipid_signal(
    ldl: Optional[float],
    total_chol: Optional[float],
    tg: Optional[float],
    hdl: Optional[float],
) -> bool:
    return bool(
        (ldl is not None and ldl > 3.0)
        or (total_chol is not None and total_chol > 5.2)
        or (tg is not None and tg > 1.7)
        or (hdl is not None and hdl < 1.0)
    )


def apob_group_row(
    *,
    has_lipid_values: bool,
    apob_g: Optional[float],
    mentioned: bool,
) -> Optional[Dict[str, str]]:
    if not has_lipid_values:
        return None
    base = (
        "АпоВ (аполипопротеин B-100) — основной белок атерогенных липопротеинов (ЛПНП, VLDL, IDL); "
        "на каждую частицу приходится одна молекула апоВ, поэтому уровень отражает число атерогенных частиц "
        "и при дислипидемии, сахарном диабете и метаболическом синдроме часто лучше стратифицирует СС-риск, "
        "чем только холестерин ЛПНП. Цели лечения и референсы задаёт врач с учётом абсолютного риска."
    )
    if apob_g is not None:
        extra = f" На бланке: {apob_g:.2f} г/л."
        if apob_g > APOB_REF_HIGH_G_L:
            extra += (
                " Выше распространённого верхнего ориентира на бланке/в лаборатории (часто до ~1.5 г/л) — "
                "усиление атерогенной нагрузки; тактика — по клинике и целевым уровням."
            )
        elif apob_g < APOB_REF_LOW_G_L:
            extra += " Ниже типичного нижнего ориентира — интерпретация с учётом лечения и редких гипобеталипопротеинемий."
        else:
            extra += " В пределах часто приводимых референсных ориентиров; динамика и целевой уровень — индивидуально."
        return {"group": "Аполипопротеин B (ApoB)", "interpretation": base + extra}
    if mentioned:
        return {
            "group": "Аполипопротеин B (ApoB)",
            "interpretation": base + " Показатель указан на бланке, числовое значение не извлечено из текста — сверка с PDF.",
        }
    return {
        "group": "Аполипопротеин B (ApoB)",
        "interpretation": base
        + " На этом бланке числовое значение апоВ не указано; при повышенном ЛПНП/non-HDL по показаниям может быть "
        "целесообразно определить апоВ (г/л) для оценки числа атерогенных частиц.",
    }


def apob_abnormal_table_row(
    apob_g: float,
    *,
    ref_low: Optional[float] = None,
    ref_high: Optional[float] = None,
) -> Dict[str, Any]:
    rl = float(APOB_REF_LOW_G_L if ref_low is None else ref_low)
    rh = float(APOB_REF_HIGH_G_L if ref_high is None else ref_high)
    direction = "high" if apob_g > rh else "low" if apob_g < rl else "normal"
    comment = "Повышен" if direction == "high" else "Снижен" if direction == "low" else "В референсе (ориентир)"
    return {
        "marker": "Аполипопротеин B (ApoB)",
        "value": f"{apob_g:.2f}",
        "ref_low": f"{rl:g}",
        "ref_high": f"{rh:g}",
        "direction": direction,
        "comment": comment,
    }


def apob_hypothesis(
    apob_g: float,
    *,
    ref_high: Optional[float] = None,
    ref_low: Optional[float] = None,
) -> Dict[str, str]:
    rh = float(APOB_REF_HIGH_G_L if ref_high is None else ref_high)
    rl = float(APOB_REF_LOW_G_L if ref_low is None else ref_low)
    if apob_g > rh:
        return {
            "hypothesis": "Повышен апоВ — усиление атерогенной частичной нагрузки",
            "basis": f"ApoB {apob_g:.2f} г/л (верх референса бланка ~{rh:g} г/л)",
            "comment": "Коррелирует с числом атерогенных липопротеинов; тактика снижения — по СС-риску и врачу.",
        }
    if apob_g < rl:
        return {
            "hypothesis": "Снижен апоВ относительно типичного референса",
            "basis": f"ApoB {apob_g:.2f} г/л",
            "comment": "Оценка в контексте терапии, всасывания, редких наследственных состояний.",
        }
    return {
        "hypothesis": "АпоВ в зоне распространённых ориентиров",
        "basis": f"ApoB {apob_g:.2f} г/л (реф. бланка ~{rl:g}–{rh:g} г/л)",
        "comment": "Интерпретация совместно с ЛПНП, non-HDL, Lp(a) и клиническим риском.",
    }


def apoa1_abnormal_table_row(
    apoa1_g: float,
    *,
    ref_low: Optional[float] = None,
    ref_high: Optional[float] = None,
) -> Dict[str, Any]:
    rl = float(APOA1_REF_LOW_G_L if ref_low is None else ref_low)
    rh = float(APOA1_REF_HIGH_G_L if ref_high is None else ref_high)
    direction = "high" if apoa1_g > rh else "low" if apoa1_g < rl else "normal"
    comment = "Повышен" if direction == "high" else "Снижен" if direction == "low" else "В референсе (ориентир)"
    return {
        "marker": "Аполипопротеин A1 (ApoA1)",
        "value": f"{apoa1_g:.2f}",
        "ref_low": f"{rl:g}",
        "ref_high": f"{rh:g}",
        "direction": direction,
        "comment": comment,
    }


def apoa1_hypothesis(
    apoa1_g: float,
    *,
    ref_high: Optional[float] = None,
    ref_low: Optional[float] = None,
) -> Dict[str, str]:
    rh = float(APOA1_REF_HIGH_G_L if ref_high is None else ref_high)
    rl = float(APOA1_REF_LOW_G_L if ref_low is None else ref_low)
    if apoa1_g > rh:
        return {
            "hypothesis": "Повышен апоА1 относительно референса бланка",
            "basis": f"ApoA1 {apoa1_g:.2f} г/л (верх референса ~{rh:g} г/л)",
            "comment": "Сопоставить с апоВ, липидной панелью и методикой лаборатории; не единоличный маркер риска.",
        }
    if apoa1_g < rl:
        return {
            "hypothesis": "Снижен апоА1 относительно референса бланка",
            "basis": f"ApoA1 {apoa1_g:.2f} г/л",
            "comment": "Интерпретация с ЛПВП и клиникой.",
        }
    return {
        "hypothesis": "АпоА1 в пределах референса бланка",
        "basis": f"ApoA1 {apoa1_g:.2f} г/л (~{rl:g}–{rh:g} г/л)",
        "comment": "Совместно с апоВ и липидами.",
    }


def apoa1_group_row(
    apoa1_g: float,
    *,
    ref_low: Optional[float] = None,
    ref_high: Optional[float] = None,
) -> Dict[str, str]:
    rl = APOA1_REF_LOW_G_L if ref_low is None else ref_low
    rh = APOA1_REF_HIGH_G_L if ref_high is None else ref_high
    base = (
        "АпоА1 — основной белок липопротеинов высокой плотности (ЛПВП); часто коррелирует с уровнем ЛПВП-ХС "
        "и рассматривается как компонент оценки баланса «атерогенные vs защитные» частицы (совместно с апоВ)."
    )
    extra = f" На бланке: {apoa1_g:.2f} г/л (реф. {rl:g}–{rh:g} г/л)."
    if apoa1_g > rh:
        extra += " Выше верхней границы референса лаборатории — интерпретация с врачом и контекстом."
    elif apoa1_g < rl:
        extra += " Ниже референса — сопоставить с ЛПВП и клиникой."
    else:
        extra += " В пределах указанного на бланке диапазона."
    return {"group": "Аполипопротеин A1 (ApoA1)", "interpretation": base + extra}


def apob_apoa1_ratio_interpretation(apob_g: float, apoa1_g: float) -> Optional[Dict[str, str]]:
    """
    Клинически используют отношение ApoB / ApoA1 (чем выше — больше доля атерогенных частиц при прочих равных).
    """
    if apoa1_g <= 0 or apob_g < 0:
        return None
    ratio = apob_g / apoa1_g
    note = (
        f"Отношение ApoB/ApoA1 ≈ {ratio:.2f} (апоВ {apob_g:.2f} г/л ÷ апоА1 {apoa1_g:.2f} г/л). "
        "Повышенное соотношение часто связывают с большей атерогенной нагрузкой; пороги зависят от лаборатории и популяции."
    )
    return {"group": "Индекс ApoB/ApoA1", "interpretation": note}


def followup_contains_apob_check(rows: List[Dict[str, Any]]) -> bool:
    for r in rows or []:
        chk = str(r.get("check") or "").lower()
        if re.search(
            r"(?:apob|apo\s*b|аполипопротеин\s*[вb]|апо\s*[-–]?\s*b\b|апо\s*в\b(?!\s*а1))",
            chk,
        ):
            return True
    return False


def ensure_apob_followup_row(
    followup: List[Dict[str, str]],
    *,
    has_lipid_values: bool,
    apob_g: Optional[float],
    atherogenic: bool,
) -> None:
    """Если есть липидные данные и апоВ не измерен — добавить явную рекомендацию на анализ (без дубликатов)."""
    if not has_lipid_values or apob_g is not None:
        return
    if followup_contains_apob_check(followup):
        return
    followup.insert(
        0,
        {
            "direction": "Липиды / сердечно-сосудистый риск",
            "check": "Аполипопротеин B (ApoB) в крови, г/л",
            "why": (
                "АпоВ отражает число атерогенных частиц (ЛПНП, VLDL, IDL); при дислипидемии и метаболическом риске "
                "часто информативнее одного только холестерина ЛПНП."
            ),
            "priority": "Высокий" if atherogenic else "Средний",
        },
    )


def merge_apob_group_into_table(
    grouped: List[Dict[str, str]],
    row: Optional[Dict[str, str]],
) -> List[Dict[str, str]]:
    if not row:
        return grouped
    new_title = (row.get("group") or "").strip().lower()
    for g in grouped:
        if (g.get("group") or "").strip().lower() == new_title:
            return grouped
    out = [row] + list(grouped)
    return out[:12]


def prepend_lipid_group_rows(
    grouped: List[Dict[str, str]],
    rows: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """Вставляет блоки интерпретации (ApoB, ApoA1, индекс) без дубликатов по заголовку группы."""
    titles = {(g.get("group") or "").strip().lower() for g in grouped if isinstance(g, dict)}
    head: List[Dict[str, str]] = []
    for row in rows:
        if not row or not isinstance(row, dict):
            continue
        t = (row.get("group") or "").strip().lower()
        if not t or t in titles:
            continue
        titles.add(t)
        head.append(row)
    return head + list(grouped)
