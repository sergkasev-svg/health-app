"""
Извлечение лабораторных показателей из текста: маркер, значение, референс, единицы, статус.
Статусы: normal, borderline_low, borderline_high, low, high, critical.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class LabValue:
    marker: str
    value: float
    unit: str
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    status: str = "normal"  # normal | borderline_low | low | significant_low | borderline_high | high | significant_high | critical
    clinical_note: str = ""
    raw_line: str = ""

    def to_abnormality_dict(self) -> Dict[str, Any]:
        return {
            "marker": self.marker,
            "value": self.value,
            "unit": self.unit,
            "status": self.status,
            "clinical_note": self.clinical_note or _default_clinical_note(self.status),
            "ref_low": self.ref_low,
            "ref_high": self.ref_high,
        }


def _default_clinical_note(status: str) -> str:
    m = {
        "low": "Ниже нормы.",
        "high": "Выше нормы.",
        "significant_low": "Значимое снижение.",
        "significant_high": "Значимое повышение.",
        "borderline_low": "Пограничное значение у нижней границы.",
        "borderline_high": "Пограничное значение у верхней границы.",
        "critical": "Критическое отклонение.",
    }
    return m.get(status, "")


# Паттерны для чисел: 26.7 или 26,7 или 40.1
_NUM = r"\d+[,.]?\d*"
# Референс: 120-160 или 4.0-10.0 или 27-31
_REF = rf"({_NUM})\s*[-–]\s*({_NUM})"


def _parse_number(s: str) -> Optional[float]:
    if not s:
        return None
    s = s.replace(",", ".").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _classify_status(
    value: float,
    ref_low: Optional[float],
    ref_high: Optional[float],
    *,
    borderline_frac: float = 0.05,
    significant_frac: float = 0.15,
) -> str:
    """Определяет статус: normal, borderline_low/high, low/high, significant_low/significant_high, critical."""
    if ref_low is None and ref_high is None:
        return "normal"
    if ref_low is not None and value < ref_low:
        delta = ref_low - value
        ref_range = (ref_high - ref_low) if (ref_high is not None and ref_high > ref_low) else (ref_low if ref_low > 0 else 1)
        if delta <= ref_range * borderline_frac:
            return "borderline_low"
        if delta <= ref_range * significant_frac:
            return "low"
        return "critical" if value < ref_low * 0.7 else "significant_low"
    if ref_high is not None and value > ref_high:
        delta = value - ref_high
        ref_range = (ref_high - ref_low) if (ref_low is not None and ref_high > ref_low) else (ref_high if ref_high > 0 else 1)
        if delta <= ref_range * borderline_frac:
            return "borderline_high"
        if delta <= ref_range * significant_frac:
            return "high"
        return "critical" if value > ref_high * 1.5 else "significant_high"
    return "normal"


def extract_cbc_values(text: str) -> List[LabValue]:
    """
    Извлекает CBC-показатели из текста.
    Поддерживает: название показателя + число на одной строке; маркер на одной строке, значение на следующей (табличный формат).
    """
    results: List[LabValue] = []
    text_lower = text.lower()
    raw_lines = text.replace("\r", "\n").split("\n")
    lines = [ln.strip() for ln in raw_lines if ln.strip()]

    # Словарь: ключевые слова для маркера -> (каноническое имя, единица по умолчанию)
    # Порядок важен: более длинные/специфичные первыми (ретикулоциты абс до ретикулоцит)
    cbc_markers: Dict[str, Tuple[str, str]] = {
        "ретикулоциты абс": ("Reticulocytes_abs", "10^9/L"),
        "ретикулоциты абс.": ("Reticulocytes_abs", "10^9/L"),
        "ретикулоцит абс": ("Reticulocytes_abs", "10^9/L"),
        "ретикулоцит абс.": ("Reticulocytes_abs", "10^9/L"),
        "reticulocytes abs": ("Reticulocytes_abs", "10^9/L"),
        "гемоглобин": ("Hb", "g/L"),
        "hb ": ("Hb", "g/L"),
        "hgb": ("Hb", "g/L"),
        "эритроцит": ("RBC", "10^12/L"),
        "rbc": ("RBC", "10^12/L"),
        "гематокрит": ("Hct", "%"),
        "hct": ("Hct", "%"),
        "mcv": ("MCV", "fL"),
        "mch": ("MCH", "pg"),
        "mchc": ("MCHC", "g/L"),
        "rdw": ("RDW", "%"),
        "лейкоцит": ("WBC", "10^9/L"),
        "wbc": ("WBC", "10^9/L"),
        "тромбоцит": ("PLT", "10^9/L"),
        "plt": ("PLT", "10^9/L"),
        # Дифференциал и абсолюты — до общих «нейтрофил/лимфоцит» (%)
        "сегментоядерн": ("Segmented_neutrophils", "%"),
        "палочкоядерн": ("Band_neutrophils", "%"),
        "нейтрофилы абсолют": ("Neutrophils_abs", "10^9/L"),
        "нейтрофилы абс": ("Neutrophils_abs", "10^9/L"),
        "нейтрофил абсолют": ("Neutrophils_abs", "10^9/L"),
        "нейтрофил абс": ("Neutrophils_abs", "10^9/L"),
        "лимфоциты абсолют": ("Lymphocytes_abs", "10^9/L"),
        "лимфоциты абс": ("Lymphocytes_abs", "10^9/L"),
        "лимфоцит абсолют": ("Lymphocytes_abs", "10^9/L"),
        "лимфоцит абс": ("Lymphocytes_abs", "10^9/L"),
        "моноциты абсолют": ("Monocytes_abs", "10^9/L"),
        "моноциты абс": ("Monocytes_abs", "10^9/L"),
        "моноцит абсолют": ("Monocytes_abs", "10^9/L"),
        "моноцит абс": ("Monocytes_abs", "10^9/L"),
        "neu#": ("Neutrophils_abs", "10^9/L"),
        "lym#": ("Lymphocytes_abs", "10^9/L"),
        "mon#": ("Monocytes_abs", "10^9/L"),
        "нейтрофил": ("Neutrophils", "%"),
        "лимфоцит": ("Lymphocytes", "%"),
        "моноцит": ("Monocytes", "%"),
        "эозинофил": ("Eosinophils", "%"),
        "базофил": ("Basophils", "%"),
        "ретикулоцит": ("Reticulocytes", "%"),
        "reticulocyte": ("Reticulocytes", "%"),
        "ret%": ("Reticulocytes_rel", "%"),
        "ret ": ("Reticulocytes_abs", "10^9/L"),
        "pdw": ("PDW", "%"),
        "рdw": ("PDW", "%"),  # кириллическая Р в «PDW» на некоторых бланках
        "ширина распределения тромбоцит": ("PDW", "%"),
        "mpv": ("MPV", "fL"),
        "p-lcr": ("P-LCR", "%"),
        "plcr": ("P-LCR", "%"),
        "соэ": ("ESR", "mm/h"),
        "esr": ("ESR", "mm/h"),
        "роэ": ("ESR", "mm/h"),
    }

    def _find_marker_in_text(s: str) -> Optional[Tuple[str, str, str]]:
        """Возвращает (canonical, unit) если в s есть ключевое слово маркера."""
        s_lower = s.lower()
        for keyword, (canon, u) in cbc_markers.items():
            if keyword in s_lower:
                return (canon, u, keyword)
        return None

    def _parse_value_and_ref(line: str) -> Optional[Tuple[float, Optional[float], Optional[float]]]:
        """Из строки извлекает первое число (значение) и опционально референс (ref_low-ref_high)."""
        value_match = re.search(rf"\b({_NUM})\b", line)
        if not value_match:
            return None
        value = _parse_number(value_match.group(1))
        if value is None:
            return None
        ref_match = re.search(_REF, line)
        ref_low, ref_high = None, None
        if ref_match:
            ref_low = _parse_number(ref_match.group(1))
            ref_high = _parse_number(ref_match.group(2))
        return (value, ref_low, ref_high)

    # 1) Табличный формат: предыдущая строка — название показателя, текущая — значение; референс может быть на этой же или следующей строке
    for i, line in enumerate(lines):
        line_lower = line.lower()
        parsed = _parse_value_and_ref(line)
        if parsed is None:
            continue
        value, ref_low, ref_high = parsed
        # Если на текущей строке только значение, референс может быть на следующей (например "115" и "120-160")
        if ref_low is None and ref_high is None and i + 1 < len(lines):
            ref_match = re.search(_REF, lines[i + 1])
            if ref_match:
                ref_low = _parse_number(ref_match.group(1))
                ref_high = _parse_number(ref_match.group(2))
        prev_line = lines[i - 1].lower() if i > 0 else ""
        num_in_line = re.search(rf"\b{_NUM}\b", line)
        pos_val = num_in_line.start() if num_in_line else 0
        prefix = line_lower[:pos_val]
        found = _find_marker_in_text(prefix)
        if not found:
            found = _find_marker_in_text(prev_line)
        if found:
            canon, unit = found[0], found[1]
            if not any(r.marker == canon for r in results):
                status = _classify_status(value, ref_low, ref_high)
                results.append(
                    LabValue(
                        marker=canon,
                        value=value,
                        unit=unit,
                        ref_low=ref_low,
                        ref_high=ref_high,
                        status=status,
                        raw_line=(prev_line + " " + line)[:200],
                    )
                )
        continue

    # 2) Классический формат: маркер и значение на одной строке (если ещё не добавлено)
    for line in lines:
        line_stripped = line.strip()
        if len(line_stripped) < 4:
            continue
        line_lower = line_stripped.lower()

        # Ищем первое число в строке (значение)
        value_match = re.search(rf"\b({_NUM})\b", line_stripped)
        if not value_match:
            continue
        value_str = value_match.group(1)
        value = _parse_number(value_str)
        if value is None:
            continue

        # Референс на этой же строке
        ref_match = re.search(_REF, line_stripped)
        ref_low, ref_high = None, None
        if ref_match:
            ref_low = _parse_number(ref_match.group(1))
            ref_high = _parse_number(ref_match.group(2))

        # Определяем маркер по ключевым словам (маркер должен быть до значения в строке)
        pos_value = value_match.start()
        prefix = line_lower[:pos_value]
        canonical = None
        unit = ""
        for keyword, (canon, u) in cbc_markers.items():
            if keyword in prefix:
                canonical = canon
                unit = u
                break
        if not canonical:
            continue

        # Избегаем дубликатов (один маркер — первое вхождение)
        if any(r.marker == canonical for r in results):
            continue

        status = _classify_status(value, ref_low, ref_high)
        results.append(
            LabValue(
                marker=canonical,
                value=value,
                unit=unit,
                ref_low=ref_low,
                ref_high=ref_high,
                status=status,
                raw_line=line_stripped[:200],
            )
        )

    # Дополнительно: абсолютные ретикулоциты (отдельная строка часто)
    if not any(r.marker == "Reticulocytes_abs" for r in results):
        abs_ret_match = re.search(
            r"ретикулоцит[^\d]*абс[^\d]*(\d+[,.]?\d*)|"
            r"reticulocytes?\s*abs[^\d]*(\d+[,.]?\d*)|"
            r"(\d+[,.]?\d*)\s*10\s*[\^\\]\s*9\s*/\s*l",
            text_lower,
            re.IGNORECASE,
        )
        if abs_ret_match:
            g = abs_ret_match.group(1) or abs_ret_match.group(2) or abs_ret_match.group(3)
            v = _parse_number(g or "")
            if v is not None and 0 < v < 500:
                results.append(
                    LabValue(
                        marker="Reticulocytes_abs",
                        value=v,
                        unit="10^9/L",
                        ref_low=50.0,
                        ref_high=None,
                        status="low" if v < 50 else "normal",
                        clinical_note="Сниженная регенераторная активность эритропоэза." if v < 50 else "",
                    )
                )

    return results
