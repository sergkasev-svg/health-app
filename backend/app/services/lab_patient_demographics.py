"""
Извлечение пола / возраста / года рождения из текста бланка и профиля API.
Используется для блока patient и уточнения limitations (педиатрия, пол).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, Optional


def _head_without_collection_dates_for_dob_heuristic(head: str) -> str:
    """Строки с датой забора/выполнения не использовать как дату рождения."""
    out_lines: list[str] = []
    for ln in (head or "").splitlines():
        if re.search(
            r"(?i)(дата\s+взятия|дата\s+забора|дата\s+выполнения|дата\s+регистрации|"
            r"дата\s+поступления|дата\s+готовности|дата\s+исследования|зарегистрирован)",
            ln,
        ):
            continue
        out_lines.append(ln)
    return "\n".join(out_lines)


def extract_patient_demographics_from_text(text: str) -> Dict[str, Any]:
    """
    Эвристики по шапке бланка: (Жен., 25.07.2012), «13 лет», явный пол.
    Подписанные поля: «Пациент:», «Пол: Ж», «Возраст: 10 л.».
    Не заменяет клиническую верификацию.
    """
    if not text or not str(text).strip():
        return {}
    head = text[:12000]
    low = head.lower()
    out: Dict[str, Any] = {}

    # ФИО (часто в первых строках бланка лаборатории)
    m_pt = re.search(
        r"(?im)^\s*пациент\s*:\s*([^\n\r]{2,120})",
        head,
    )
    if m_pt:
        name = re.sub(r"\s+", " ", m_pt.group(1).strip())
        if name and not re.match(r"^\d", name):
            out["display_name"] = name

    # Пол: Ж / Пол: М — часто одна буква после двоеточия (лабораторные бланки РФ)
    for _ln in head.splitlines()[:80]:
        ln = _ln.strip()
        m_pol_line = re.match(r"(?i)пол\s*:\s*(.+)$", ln)
        if not m_pol_line:
            continue
        val = m_pol_line.group(1).strip().rstrip(".").lower()
        if val in ("ж", "жен", "жен.", "женский", "female", "f", "w"):
            out["sex"] = "женский"
        elif val in ("м", "муж", "муж.", "мужской", "male", "m"):
            out["sex"] = "мужской"
        break

    if "sex" not in out:
        # Пол: типичные формы в шапке РФ (скобки, запятая после «Жен.»)
        if (
            re.search(r"\([Жж]ен\.", head)
            or re.search(r"\b[Жж]ен\.\s*,", head[:1200])
            or re.search(r"\bжен\.?\s*,", head[:800])
        ):
            out["sex"] = "женский"
        elif re.search(r"\([Мм]уж\.", head) or re.search(r"\bмуж\.?\s*,", head[:800]):
            out["sex"] = "мужской"
    # Не используем подстроку «мужской»/«женский» в первых N символах: в бланках часто
    # «норма для мужчин», «референс мужской» — это не пол пациента.
    if "sex" not in out:
        m_ps = re.search(r"(?im)^\s*пол\s+(женский|мужской)\b", head[:6000])
        if m_ps:
            out["sex"] = (
                "женский" if "жен" in m_ps.group(1).lower() else "мужской"
            )
        elif re.search(r"(?i)\bпол\s+женск", head[:4000]) and not re.search(
            r"(?i)\bпол\s+мужск", head[:4000]
        ):
            out["sex"] = "женский"
        elif re.search(r"(?i)\bпол\s+мужск", head[:4000]):
            out["sex"] = "мужской"
    if "sex" not in out:
        # Только явные англ. маркеры в шапке (не внутри длинного текста референсов)
        head_top = "\n".join(head.splitlines()[:25])
        low_top = head_top.lower()
        if re.search(r"\bfemale\b", low_top):
            out["sex"] = "женский"
        elif re.search(r"\bmale\b", low_top):
            out["sex"] = "мужской"

    # Возраст: 10 л. / 10 л (лабораторный сокращённый формат)
    m_vl = re.search(
        r"(?im)^\s*возраст\s*:\s*(\d{1,3})\s*л\.?\b",
        head,
    )
    if m_vl:
        try:
            a = int(m_vl.group(1))
            if 0 < a < 120:
                out["age_years"] = a
        except (ValueError, IndexError):
            pass

    # Возраст: 45 / 45 лет / 45 полных лет (без обязательного «л.»)
    if out.get("age_years") is None:
        m_va = re.search(
            r"(?im)^\s*возраст\s*:\s*(\d{1,3})(?:\s*(?:л\.?|лет|года?|г\.|полных\s+лет))?\b",
            head,
        )
        if m_va:
            try:
                a = int(m_va.group(1))
                if 0 < a < 120:
                    out["age_years"] = a
            except (ValueError, IndexError):
                pass
    if out.get("age_years") is None:
        m_vd = re.search(
            r"(?i)возраст\s+(?:на\s+дату\s+(?:забора|взятия)\s*)?[:\s]+\s*(\d{1,3})\b",
            head[:5000],
        )
        if m_vd:
            try:
                a = int(m_vd.group(1))
                if 0 < a < 120:
                    out["age_years"] = a
            except (ValueError, IndexError):
                pass

    # Явная дата рождения по подписи (не эвристика по первой дате в тексте)
    if "birth_year" not in out or out.get("age_years") is None:
        m_dob_lbl = re.search(
            r"(?i)(?:дата\s+рождения|д\.?\s*р\.?|родил[аи]с[ья])\s*[:\s]+"
            r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})\b",
            head[:10000],
        )
        if m_dob_lbl:
            try:
                _d, _mo, yraw = m_dob_lbl.group(1), m_dob_lbl.group(2), m_dob_lbl.group(3)
                yi = int(yraw)
                if len(yraw) == 2:
                    yi = int("20" + yraw) if int(yraw) < 70 else int("19" + yraw)
                if 1920 <= yi <= date.today().year:
                    out["birth_year"] = yi
                    if out.get("age_years") is None:
                        out["age_years"] = max(0, date.today().year - yi)
            except (ValueError, IndexError):
                pass

    # Дата рождения в скобках (Жен., 25.07.2012) — типичный формат лабораторий
    m_paren_dob = re.search(
        r"\([Жж]ен\.,\s*(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\s*\)",
        head[:4000],
    )
    if not m_paren_dob:
        m_paren_dob = re.search(
            r"\([Мм]уж\.,\s*(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\s*\)",
            head[:4000],
        )
    if m_paren_dob:
        try:
            y = int(m_paren_dob.group(3))
            if 1920 <= y <= date.today().year:
                out["birth_year"] = y
        except (ValueError, IndexError):
            pass

    # «N лет» в шапке — раньше эвристики по «первой дате» (часто дата анализа, не ДР)
    if out.get("age_years") is None:
        m_age = re.search(r"(\d{1,3})\s*лет\b", low[:2500])
        if m_age:
            try:
                a = int(m_age.group(1))
                if 0 < a < 120:
                    out["age_years"] = a
            except (ValueError, IndexError):
                pass

    # Дата рождения DD.MM.YYYY — не брать из строк «дата взятия/забора»; не путать с датой исследования
    if out.get("age_years") is None:
        head_for_dob = _head_without_collection_dates_for_dob_heuristic(head)
        for m in re.finditer(
            r"(\d{1,2})[.\-/](\d{1,2})[.\-/](20[0-4]\d|19\d{2})",
            head_for_dob[:8000],
        ):
            try:
                y = int(m.group(3))
                if y < 1950 or y > date.today().year:
                    continue
                if y >= date.today().year - 15:
                    continue
                out["birth_year"] = y
                out["age_years"] = date.today().year - y
                break
            except (ValueError, IndexError):
                pass

    # Год рождения отдельно: г.р. 2012, рожд. 2012
    if "birth_year" not in out and out.get("age_years") is None:
        m_by = re.search(
            r"(?:г\.?\s*р\.?|рожд\.?|год\s+рожд)[^\d]{0,12}(20[0-4]\d|19\d{2})\b",
            low,
            re.IGNORECASE,
        )
        if m_by:
            try:
                y = int(m_by.group(1))
                if 1900 <= y <= date.today().year:
                    out["birth_year"] = y
                    out["age_years"] = date.today().year - y
            except (ValueError, IndexError):
                pass

    # Если возраст в тексте не указан, но есть год рождения — грубая оценка по текущему году
    if out.get("age_years") is None and out.get("birth_year") is not None:
        try:
            y = int(out["birth_year"])
            if 1910 <= y <= date.today().year:
                out["age_years"] = max(0, date.today().year - y)
        except (TypeError, ValueError):
            pass

    return out


def _normalize_date_display(raw: str) -> str:
    """Приводит дату к виду ДД.ММ.ГГГГ для отображения."""
    s = (raw or "").strip()
    m = re.match(r"^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})$", s)
    if not m:
        return s
    d, mo, y = m.group(1), m.group(2), m.group(3)
    if len(y) == 2:
        y = "20" + y if int(y) < 70 else "19" + y
    return f"{int(d):02d}.{int(mo):02d}.{y}"


def extract_lab_metadata_from_text(text: str) -> Dict[str, Any]:
    """
    Биоматериал, дата забора, дата выполнения — типичные поля шапки РФ-лабораторий.
    """
    if not text or not str(text).strip():
        return {}
    head = text[:14000]
    out: Dict[str, Any] = {}

    # Биоматериал / материал / проба (строка после метки)
    for rx in (
        r"(?:биоматериал|материал\s*биологическ|материал)[:\s]+([^\n\r]{2,100})",
        r"(?:проба|тип\s+пробы|вид\s+материала)[:\s]+([^\n\r]{2,90})",
    ):
        m = re.search(rx, head, re.IGNORECASE)
        if not m:
            continue
        val = m.group(1).strip()
        val = re.sub(r"\s+", " ", val).strip(" \t.;,")
        val = re.split(r"\s+(?:дата|забор|выполн)", val, maxsplit=1, flags=re.I)[0].strip()
        if len(val) > 2 and len(val) < 120 and not re.match(r"^\d{1,2}[.\-/]", val):
            out["sample_type"] = val
            break

    if "sample_type" not in out:
        # Явные короткие формулировки в первых строках
        m = re.search(
            r"(?m)^[^\n]*(венозн\w*\s+кровь|капиллярн\w*\s+кровь|кровь\s+венозн|сыворотка|плазма|моча\s|кал\s|слюн)",
            head[:3500],
            re.IGNORECASE,
        )
        if m:
            frag = m.group(0).strip()
            frag = re.sub(r"^[^А-Яа-яA-Za-z]*", "", frag)
            if 3 < len(frag) < 80:
                out["sample_type"] = frag[:100]

    def _date_after_label(pattern: str) -> Optional[str]:
        m = re.search(pattern, head, re.IGNORECASE | re.DOTALL)
        if not m:
            return None
        return _normalize_date_display(m.group(1))

    def _iso_after_label(pattern: str) -> Optional[str]:
        m = re.search(pattern, head, re.IGNORECASE | re.DOTALL)
        if not m:
            return None
        y, mo, d = m.group(1), m.group(2), m.group(3)
        try:
            return f"{int(d):02d}.{int(mo):02d}.{y}"
        except (ValueError, TypeError):
            return None

    # Дата забора / взятия
    cd = _date_after_label(
        r"(?:дата\s+забора|дата\s+взятия|забор\s+пробы|дата\s+взятия\s+пробы|дата\s+забора\s+пробы|"
        r"взятие\s+биоматериала)"
        r"[^\d]{0,40}(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})"
    )
    if cd:
        out["collection_date"] = cd
    if "collection_date" not in out:
        icd = _iso_after_label(
            r"(?:дата\s+забора|дата\s+взятия)[^\d]{0,40}(\d{4})-(\d{2})-(\d{2})\b"
        )
        if icd:
            out["collection_date"] = icd

    # Дата выполнения / исследования / регистрации / готовности
    rd = _date_after_label(
        r"(?:дата\s+выполнения(?:\s+исследования)?|дата\s+исследования|дата\s+регистрации|дата\s+поступления|"
        r"дата\s+готовности|дата\s+выдачи|дата\s+печати|результат\s+от|зарегистрирован)"
        r"[^\d]{0,80}(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})"
    )
    if rd:
        out["report_date"] = rd
    if "report_date" not in out:
        ird = _iso_after_label(
            r"(?:дата\s+выполнения|дата\s+исследования|зарегистрирован)[^\d]{0,60}(\d{4})-(\d{2})-(\d{2})\b"
        )
        if ird:
            out["report_date"] = ird

    # Общие «Дата: …» в шапке — по порядку: забор, затем выполнение
    if "collection_date" not in out or "report_date" not in out:
        generic_dates = re.findall(
            r"(?:дата|date)[:\s]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
            head[:6000],
            re.IGNORECASE,
        )
        uniq: list[str] = []
        for d in generic_dates:
            nd = _normalize_date_display(d)
            if nd and nd not in uniq:
                uniq.append(nd)
        if "collection_date" not in out and uniq:
            out["collection_date"] = uniq[0]
        if "report_date" not in out and len(uniq) >= 2:
            out["report_date"] = uniq[1]

    # «Дата:» в одну строку (часто без слов «забор»/«выполнение»)
    if "collection_date" not in out:
        m_short = re.search(
            r"(?im)^\s*дата\s*:\s*(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})\b",
            head[:9000],
        )
        if m_short:
            out["collection_date"] = _normalize_date_display(m_short.group(1))

    # Одна дата в шапке — часто совпадает с датой готовности результата
    if out.get("collection_date") and not out.get("report_date"):
        out["report_date"] = out["collection_date"]

    return out


def _normalize_sex(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    if s in ("f", "female", "ж", "жен", "женский", "жен."):
        return "женский"
    if s in ("m", "male", "м", "муж", "мужской", "муж."):
        return "мужской"
    if "жен" in s:
        return "женский"
    if "муж" in s:
        return "мужской"
    return str(raw).strip()


def _sync_document_summary_meta(report: Dict[str, Any]) -> None:
    """Дублирует ключевые поля patient в document_summary для HTML-шапки отчёта."""
    keys = ("display_name", "sex", "age_years", "birth_year", "sample_type", "collection_date", "report_date")
    pat = report.get("patient") or {}
    ds = dict(report.get("document_summary") or {})
    for k in keys:
        v = pat.get(k)
        if v is None:
            continue
        sv = str(v).strip()
        if not sv or sv == "—":
            continue
        ds[k] = v
    report["document_summary"] = ds


def enrich_report_with_patient_demographics(
    report: Dict[str, Any],
    extracted: str,
    profile: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Заполняет report['patient'] и дополняет limitations с учётом текста и profile.
    Мутирует report.
    """
    demo = extract_patient_demographics_from_text(extracted)
    lab_meta = extract_lab_metadata_from_text(extracted)
    for k, v in lab_meta.items():
        if v:
            demo[k] = v
    prof = dict(profile or {})

    # Пол / возраст / год рождения — только с бланка (OCR). Не подставляем из ЛК: часто другой человек.
    # В шапке отчёта при отсутствии данных — «—».

    st = prof.get("sample_type") or prof.get("biomaterial")
    if st:
        demo.setdefault("sample_type", str(st).strip())
    for dk in ("collection_date", "report_date"):
        pv = prof.get(dk)
        if pv:
            demo.setdefault(dk, str(pv).strip())

    pat_existing = dict(report.get("patient") or {})
    for k, v in demo.items():
        if v is not None and v != "":
            pat_existing[k] = v
    report["patient"] = pat_existing

    _sync_document_summary_meta(report)
    _append_contextual_limitations(report)


def _limitation_row_text(x: Any) -> str:
    """Строка для сравнения: и str, и dict (organic acids и др.)."""
    if isinstance(x, dict):
        return str(x.get("limitation") or x.get("title") or x.get("value") or "")
    return str(x or "")


def _append_contextual_limitations(report: Dict[str, Any]) -> None:
    pat = report.get("patient") or {}
    lim = list(report.get("limitations") or [])

    sex = pat.get("sex")
    age = pat.get("age_years")
    by = pat.get("birth_year")

    extra: list[str] = []

    if sex and "жен" in str(sex).lower():
        extra.append(
            "Учтено: пол женский — референсы и интерпретация части показателей могут отличаться от мужских; окончательная оценка — врачом."
        )
    elif sex and "муж" in str(sex).lower():
        extra.append(
            "Учтено: пол мужской — референсы и интерпретация части показателей с учётом пола; окончательная оценка — врачом."
        )

    if age is not None:
        try:
            ai = int(float(age))
            if ai < 18:
                extra.append(
                    f"Учтено: возраст около {ai} лет (несовершеннолетний пациент) — целевые уровни липидов и ряд норм задаются педиатрическими референсами; интерпретация «как у взрослого» без врача недопустима."
                )
        except (TypeError, ValueError):
            pass

    if by is not None:
        try:
            extra.append(
                f"Год рождения (бланк/профиль): {int(by)} — возраст для справки оценён приблизительно от текущей даты."
            )
        except (TypeError, ValueError):
            pass

    for e in extra:
        if not any((e[:55] in _limitation_row_text(x)) for x in lim):
            lim.append(e)

    base_lipid = (
        "Интерпретация липидного профиля требует учёта возраста, пола, факторов риска и клинической картины."
    )
    doc_t = str(report.get("doc_type") or report.get("document_type") or "")
    if doc_t in ("lipid_panel", "biochemistry_blood", "biochemistry") or "липид" in doc_t.lower():
        if not any(base_lipid in _limitation_row_text(x) for x in lim):
            lim.insert(0, base_lipid)

    report["limitations"] = lim
