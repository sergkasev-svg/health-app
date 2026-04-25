"""
Парсер отчётов органических кислот в моче (ГХ-МС).
Возвращает doc_type, patient, markers, source_limitations, quality_notes.

Цели:
- лучше держать многосекционный документ
- не терять маркеры со 2-5 страниц
- помечать неполное распознавание
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

INVALID_ANALYTE_PATTERNS = (
    r"\.pdf$",
    r"оргкислоты\.pdf",
    r"окисления жирных кислот",
    r"маркеры углеводного обмена",
    r"маркеры метаболизма",
    r"^в т\.ч\.?",
    r"^анализ$",
    r"^результат$",
)

SECTION_CATEGORY_MAP = {
    "маркеры углеводного обмена": "Кетоновые тела и углеводный обмен",
    "маркеры кетогенеза": "Кетоновые тела и углеводный обмен",
    "маркеры метаболизма в цикле трикарбоновых кислот": "Метаболиты цикла Кребса",
    "в цикле кребса": "Метаболиты цикла Кребса",
    "маркеры метаболизма разветвленных аминокислот": "Аминокислотный обмен",
    "маркеры метаболизма ароматических аминокислот": "Аминокислотный обмен",
    "маркеры метаболизма триптофана": "Витамин-зависимые маркеры",
    "маркеры достаточности витаминов": "Витамин-зависимые маркеры",
    "маркеры достаточности витамина": "Витамин-зависимые маркеры",
    "маркеры детоксикации и эндогенной интоксикации": "Маркеры детоксикации и токсического воздействия",
    "маркеры интоксикации производными бензола": "Маркеры детоксикации и токсического воздействия",
    "бактериальные маркеры дисбиоза кишечника": "Маркеры детоксикации и токсического воздействия",
    "дрожжевые и грибковые маркеры дисбиоза кишечника": "Маркеры детоксикации и токсического воздействия",
}

SECTION_HINTS = tuple(SECTION_CATEGORY_MAP.keys())


def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        s = str(x).strip().replace(",", ".")
        return float(s)
    except (TypeError, ValueError):
        return None


def _marker_category(name: str, current_section: str = "") -> str:
    sec = (current_section or "").lower()
    for k, v in SECTION_CATEGORY_MAP.items():
        if k in sec:
            return v

    low = (name or "").lower()
    if any(
        k in low
        for k in (
            "цитрат",
            "лимонн",
            "изоцитрат",
            "янтар",
            "сукцин",
            "фумар",
            "яблоч",
            "малат",
            "аконит",
            "кетоглутар",
        )
    ):
        return "Метаболиты цикла Кребса"
    if any(k in low for k in ("малонов", "гидроксимасля", "ацетоуксус", "лактат", "пируват")):
        return "Кетоновые тела и углеводный обмен"
    if any(
        k in low
        for k in (
            "гиппур",
            "метилгиппур",
            "миндальн",
            "бензойн",
            "кофейн",
            "фенилглиокс",
            "пара-гидроксибенз",
            "трикарбал",
        )
    ):
        return "Маркеры детоксикации и токсического воздействия"
    if any(
        k in low
        for k in (
            "ксантурен",
            "метилмалон",
            "формиминоглутамин",
            "кинурен",
            "квинолин",
            "пиколин",
            "оротов",
        )
    ):
        return "Витамин-зависимые маркеры"
    return "Аминокислотный обмен"


def _is_valid_metabolite_name(name: str) -> bool:
    s = (name or "").strip()
    if not s or len(s) < 5:
        return False
    low = s.lower()
    for pat in INVALID_ANALYTE_PATTERNS:
        if re.search(pat, low, re.I):
            return False
    if not any(ch.isalpha() for ch in s):
        return False
    if low.endswith(".pdf") or low.startswith("в т.ч"):
        return False
    return True


def _clean_marker_name(line: str) -> str:
    s = re.sub(r"\s+", " ", str(line or "")).strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith("("):
        return ""
    if ")" in s and "(" not in s:
        return ""
    if "(" in s:
        s = s.split("(", 1)[0].strip()
    s = re.sub(r"\b(ммоль/моль|ммоль/л|отн\.ед\./моль)\b.*$", "", s, flags=re.I).strip()
    s = s.rstrip(":;,. ").strip()
    if s.lower() in {"кислота", "кислоты"}:
        return ""
    return s


def _extract_patient(text: str) -> Dict[str, Any]:
    patient: Dict[str, Any] = {}
    text_low = (text or "").lower()
    lines = [ln.strip() for ln in text.splitlines() if ln and ln.strip()]

    for line in lines:
        line_low = line.lower()
        if "пол:" in line_low or "пол " in line_low:
            val = line.split(":", 1)[-1].strip() if ":" in line else ""
            val_low = val.lower()
            if "жен" in val_low or val_low in ("ж", "f", "female"):
                patient["sex"] = "Ж"
                break
            if "муж" in val_low or val_low in ("м", "m", "male"):
                patient["sex"] = "М"
                break

    age_match = re.search(r"(\d+)\s*(?:лет|л\.)", text_low)
    if age_match:
        patient["age_years"] = int(age_match.group(1))
    else:
        m = re.search(r"возраст[:\s]+(\d+)", text_low)
        if m:
            patient["age_years"] = int(m.group(1))

    if "моча" in text_low or "моче" in text_low:
        patient["sample_type"] = "Моча разовая"

    def _iso_from_groups(d: str, mth: str, y: str) -> str:
        year = int(y) if len(y) == 4 else (2000 + int(y) if int(y) < 100 else int(y))
        return f"{year:04d}-{int(mth):02d}-{int(d):02d}"

    date_num = r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})"
    col_m = re.search(rf"(?i)дата\s*взятия[\s:]*{date_num}", text)
    rep_m = re.search(rf"(?i)дата\s*выполнен\w*[\s:]*{date_num}", text)

    if col_m:
        patient["collection_date"] = _iso_from_groups(col_m.group(1), col_m.group(2), col_m.group(3))
    if rep_m:
        patient["report_date"] = _iso_from_groups(rep_m.group(1), rep_m.group(2), rep_m.group(3))

    if not patient.get("collection_date") or not patient.get("report_date"):
        matches = list(re.finditer(date_num, text))
        dates: List[str] = []
        for m in matches:
            dates.append(_iso_from_groups(m.group(1), m.group(2), m.group(3)))
        if dates:
            if not patient.get("collection_date"):
                patient["collection_date"] = dates[0]
            if not patient.get("report_date"):
                patient["report_date"] = dates[-1] if len(dates) > 1 else dates[0]

    return patient


def _is_section_header(line: str) -> bool:
    low = (line or "").lower()
    return any(h in low for h in SECTION_HINTS)


def _extract_markers(text: str) -> List[Dict[str, Any]]:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln and ln.strip()]
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    current_section = ""

    i = 0
    while i < len(lines):
        line = lines[i]
        low = line.lower()

        if _is_section_header(line):
            current_section = line
            i += 1
            continue

        if "кислот" not in low and "кислоты" not in low:
            i += 1
            continue
        if low.startswith(("маркеры ", "результатов ", "обязательна ", "в т.ч", "креатинин")):
            i += 1
            continue

        name = _clean_marker_name(line)
        if not name or not _is_valid_metabolite_name(name):
            i += 1
            continue

        nums: List[float] = []
        end_j = i
        for j in range(i, min(i + 10, len(lines))):
            vals = re.findall(r"-?\d+[.,]?\d*", lines[j])
            for v in vals:
                f = _to_float(v)
                if f is not None:
                    nums.append(f)
            end_j = j
            if len(nums) >= 3:
                break

        if len(nums) < 3:
            i += 1
            continue

        ref_low, ref_high, value = nums[0], nums[1], nums[2]
        if ref_high <= ref_low:
            i += 1
            continue

        key = name.lower()
        if key in seen:
            i += 1
            continue

        flag = "normal"
        if value > ref_high:
            flag = "high"
        elif value < ref_low:
            flag = "low"
        else:
            ratio = (value - ref_low) / (ref_high - ref_low)
            if ratio >= 0.85:
                flag = "near_upper"

        seen.add(key)

        note = ""
        for j in range(i + 1, min(end_j + 3, len(lines))):
            low_j = lines[j].lower()
            if low_j.startswith("в т.ч"):
                note = lines[j].replace("В т.ч.", "").strip()[:220]
                break

        out.append(
            {
                "name": name,
                "category": _marker_category(name, current_section=current_section),
                "value": value,
                "ref_low": ref_low,
                "ref_high": ref_high,
                "flag": flag,
                "note": note,
                "section": current_section,
            }
        )
        i += 1

    return out


def _build_quality_notes(text: str, markers: List[Dict[str, Any]]) -> List[str]:
    notes: List[str] = []
    low = (text or "").lower()
    section_hits = sum(1 for hint in SECTION_HINTS if hint in low)
    abnormal_count = sum(1 for m in markers if str(m.get("flag", "")).lower() in ("high", "low"))

    if section_hits >= 4 and len(markers) < 10:
        notes.append("Возможна неполная экстракция текста: распознано слишком мало маркеров для многораздельного отчёта.")
    if "стр. 2/6" in low or "стр. 3/6" in low or "стр. 4/6" in low or "стр. 5/6" in low:
        if abnormal_count <= 1:
            notes.append("В документе несколько страниц, но найдено слишком мало отклонений; стоит проверить OCR/извлечение PDF.")
    return notes


def parse_organic_acids(
    text: str,
    filename: str = "",
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    text = (text or "").strip()
    profile = profile or {}

    patient = _extract_patient(text)
    markers = _extract_markers(text)

    if not patient.get("sex") and profile.get("sex"):
        s = str(profile.get("sex", "")).lower()
        patient["sex"] = "Ж" if "female" in s or "ж" in s else "М"

    if not patient.get("age_years") and profile.get("date_of_birth"):
        try:
            patient["age_years"] = 2025 - int(str(profile.get("date_of_birth", ""))[:4])
        except Exception:
            pass

    if not patient.get("sample_type"):
        patient["sample_type"] = "Моча разовая"

    quality_notes = _build_quality_notes(text, markers)

    return {
        "doc_type": "organic_acids_urine",
        "patient": patient,
        "markers": markers,
        "quality_notes": quality_notes,
        "source_limitations": [
            "Результатов исследования недостаточно для постановки диагноза.",
            "Требуется очная интерпретация врачом.",
        ],
    }
