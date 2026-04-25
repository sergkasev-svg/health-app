"""
Специализированный парсер отчётов органических кислот в моче (ГХ-МС).
Извлечение данных пациента из документа, аномальных маркеров, без галлюцинаций.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# Фразы для определения типа документа
ORGANIC_ACIDS_ROUTE_PHRASES = (
    "органические кислоты в моче",
    "гх-мс",
    "маркеры углеводного обмена",
    "маркеры метаболизма",
)


def is_organic_acids_urine_document(text: str) -> bool:
    """Проверяет, является ли документ отчётом органических кислот в моче."""
    low = (text or "").lower()
    return any(phrase in low for phrase in ORGANIC_ACIDS_ROUTE_PHRASES)


# Запрещённые гипотезы/диагнозы без явной связи с данными
SUPPRESSED_HALLUCINATIONS = [
    "липид",
    "холестер",
    "железодефицит",
    "железодефицитная анемия",
    "анемия железодефици",
    "высокий кортизол",
    "кортизол",
    "нарушение сна",
    "бессонниц",
    "инсомни",
    "гистамин",
    "непереносимость гистамина",
    "цитрус",
    "вин",
    "сыр",
    "шоколад",
    "пищевые триггеры",
    "инфекция мочевыводящих",
    "цистит",
    "пиелонефрит",
    "мигрен",
]


# Имена, не являющиеся метаболитами (артефакты парсинга)
INVALID_ANALYTE_PATTERNS = (
    r"\.pdf$",
    r"оргкислоты\.pdf",
    r"окисления жирных кислот",
    r"маркеры углеводного обмена",
    r"маркеры метаболизма",
    r"^гипотеза:\s*гипотеза:",
    r"^\s*•\s*•\s*$",
)


def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        s = str(x).strip().replace(",", ".")
        return float(s)
    except (TypeError, ValueError):
        return None


def _is_valid_metabolite_name(name: str) -> bool:
    """Проверяет, что имя не является артефактом парсинга."""
    s = (name or "").strip()
    if not s or len(s) < 5:
        return False
    low = s.lower()
    for pat in INVALID_ANALYTE_PATTERNS:
        if re.search(pat, low, re.I):
            return False
    if not any(ch.isalpha() for ch in s):
        return False
    if low.endswith(".pdf"):
        return False
    return True


def _extract_patient_from_document(text: str) -> Dict[str, Any]:
    """Извлекает данные пациента из текста документа."""
    patient: Dict[str, Any] = {}
    text_low = (text or "").lower()
    lines = [ln.strip() for ln in text.splitlines() if ln and ln.strip()]

    # Пол
    for i, line in enumerate(lines):
        line_low = line.lower()
        if "пол:" in line_low or "пол " in line_low or "sex:" in line_low:
            val = line.split(":", 1)[-1].strip() if ":" in line else line.strip()
            val_low = val.lower()
            if "жен" in val_low or val_low in ("ж", "f", "female"):
                patient["sex"] = "Ж"
                break
            if "муж" in val_low or val_low in ("м", "m", "male"):
                patient["sex"] = "М"
                break
    if not patient.get("sex"):
        for line in lines:
            line_low = line.lower()
            if "женский" in line_low:
                patient["sex"] = "Ж"
                break
            if "мужской" in line_low:
                patient["sex"] = "М"
                break

    # Возраст
    age_match = re.search(r"(\d+)\s*лет", text_low)
    if age_match:
        patient["age_years"] = int(age_match.group(1))
    if not patient.get("age_years"):
        age_match = re.search(r"возраст[:\s]+(\d+)", text_low)
        if age_match:
            patient["age_years"] = int(age_match.group(1))

    # Тип биоматериала
    if "моча" in text_low or "моче" in text_low:
        patient["sample_type"] = "Моча разовая"
    for phrase in ("биоматериал:", "биоматериал ", "образец:"):
        for line in lines:
            if phrase in line.lower():
                patient["sample_type"] = line.split(":", 1)[-1].strip() if ":" in line else line.strip()
                break

    # Даты
    date_pattern = r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})"
    date_matches = list(re.finditer(date_pattern, text))
    if date_matches:
        dates = []
        for m in date_matches:
            d, mth, y = m.group(1), m.group(2), m.group(3)
            year = int(y) if len(y) == 4 else 2000 + int(y) if int(y) < 100 else int(y)
            dates.append(f"{year:04d}-{int(mth):02d}-{int(d):02d}")
        if len(dates) >= 2:
            patient["collection_date"] = dates[0]
            patient["report_date"] = dates[1]
        elif dates:
            patient["collection_date"] = dates[0]
            patient["report_date"] = dates[0]

    return patient


def _extract_abnormal_markers(text: str) -> List[Dict[str, Any]]:
    """Извлекает аномальные маркеры из текста (значение выше/ниже референса)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln and ln.strip()]
    out: List[Dict[str, Any]] = []
    seen: set = set()

    i = 0
    while i < len(lines):
        line = lines[i]
        low = line.lower()
        if "кислот" not in low and "кислоты" not in low:
            i += 1
            continue
        if low.startswith("маркеры ") or low.startswith("результатов ") or low.startswith("обязательна "):
            i += 1
            continue

        name = _clean_marker_name(line)
        if not name or not _is_valid_metabolite_name(name):
            i += 1
            continue

        nums: List[float] = []
        end_idx = i
        for j in range(i, min(i + 16, len(lines))):
            line_j = lines[j]
            vals = re.findall(r"-?\d+[.,]?\d*", line_j)
            for v in vals:
                f = _to_float(v)
                if f is not None:
                    nums.append(f)
            end_idx = j
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

        status = "normal"
        if value > ref_high:
            status = "high"
        elif value < ref_low:
            status = "low"

        if status == "normal":
            i += 1
            continue

        seen.add(key)
        unit = "ммоль/моль креатинина"
        for u in ("ммоль/моль", "ммоль/л", "отн.ед."):
            if u in line.lower() or (j > i and u in lines[j].lower()):
                unit = u
                break

        out.append({
            "marker": name,
            "value": value,
            "ref_low": ref_low,
            "ref_high": ref_high,
            "unit": unit,
            "direction": status,
            "comment": "",
        })
        if len(out) >= 15:
            break
        i += 1

    return out


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


def _suppress_hallucinations(items: List[str]) -> List[str]:
    """Удаляет из списка запрещённые гипотезы."""
    out: List[str] = []
    for x in items or []:
        s = str(x or "").strip()
        if not s:
            continue
        low = s.lower()
        if any(supp in low for supp in SUPPRESSED_HALLUCINATIONS):
            continue
        out.append(s)
    return out


def parse_organic_acids_urine(
    text: str,
    filename: str = "",
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Парсит отчёт органических кислот в моче.
    Возвращает структурированный объект для physician report.
    """
    text = (text or "").strip()
    profile = profile or {}

    patient = _extract_patient_from_document(text)
    abnormal_findings = _extract_abnormal_markers(text)

    profile_conflict = False
    profile_sex = profile.get("sex") or profile.get("gender")
    profile_dob = profile.get("date_of_birth") or profile.get("birth_date")
    if patient.get("sex") and profile_sex:
        profile_sex_low = str(profile_sex).lower()
        doc_sex = str(patient.get("sex", "")).strip()
        if ("female" in profile_sex_low or "ж" in profile_sex_low) and doc_sex != "Ж":
            profile_conflict = True
        if ("male" in profile_sex_low or "м" in profile_sex_low) and doc_sex != "М":
            profile_conflict = True
    if patient.get("age_years") and profile_dob:
        try:
            from datetime import datetime
            birth_year = int(str(profile_dob)[:4])
            profile_age = datetime.now().year - birth_year
            if abs(profile_age - patient["age_years"]) > 5:
                profile_conflict = True
        except Exception:
            pass

    if not patient.get("sex") and profile_sex:
        patient["sex"] = "Ж" if "female" in str(profile_sex).lower() or "ж" in str(profile_sex).lower() else "М"
    if not patient.get("age_years") and profile_dob:
        try:
            from datetime import datetime
            patient["age_years"] = datetime.now().year - int(str(profile_dob)[:4])
        except Exception:
            pass
    if not patient.get("sample_type"):
        patient["sample_type"] = "Моча разовая"

    return {
        "document_type": "organic_acids_urine",
        "patient": patient,
        "summary": "Структурированный отчёт по органическим кислотам в моче.",
        "abnormal_findings": abnormal_findings[:15],
        "interpretation": [
            "Профиль содержит несколько повышенных органических кислот.",
            "Изолированно такие показатели не устанавливают диагноз.",
            "Интерпретация возможна только в контексте жалоб, питания, лекарств, экспозиций и очного осмотра.",
        ],
        "follow_up": {
            "tests": [],
            "referrals": ["Консультация лечащего врача / педиатра.", "Повторная клиническая оценка в контексте симптомов."],
            "notes": ["При необходимости врач решает вопрос о целевых дообследованиях по выявленным группам отклонений."],
        },
        "limitations": [
            "Результатов исследования недостаточно для постановки диагноза.",
            "Требуется очная интерпретация врачом.",
        ],
        "debug": {
            "profile_conflict": profile_conflict,
            "suppressed_hallucinations": SUPPRESSED_HALLUCINATIONS[:10],
        },
    }
