"""
Форматирование врачебного отчёта по документу.
Для organic_acids_urine — маршрут в отдельный pipeline с таблицами.

Важно:
- format_document_physician_report() возвращает ТОЛЬКО plain text
- HTML лежит отдельно в physician_report_html
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.document_routes.organic_acids_route import (
    route_organic_acids,
    build_organic_acids_report,
    filename_suggests_organic_acids,
)
from app.services.organic_acids_urine_parser import (
    is_organic_acids_urine_document,
    parse_organic_acids_urine,
)
from app.services.document_type_detector import (
    classify_by_cbc_markers,
    detect_report_type,
    _count_biochem_matches,
)
from app.services.clinical_engine.material_protocols.material_router import route_document
from app.services.lipid_engine import build_lipid_report
from app.services.cbc_engine import build_cbc_report
from app.services.lab_value_extractor import LabValue as CbcLabValue, extract_cbc_values
from app.services.clinical_engine import run_blood_biochemistry_pipeline, report_model_to_legacy_dict
from app.services.urinalysis_engine import build_urinalysis_report
from app.services.lab_patient_demographics import (
    enrich_report_with_patient_demographics,
)
from app.services.cbc_display_labels import (
    cbc_abnormal_row_dedup_key,
    cbc_label_ru,
)


def _abnormal_row_key(row: Dict[str, Any]) -> str:
    return cbc_abnormal_row_dedup_key(row) if isinstance(row, dict) else ""


def _abnormal_rows_lipid_and_nonlipid_blood(rows: List[Dict[str, Any]]) -> bool:
    """
    True, если в таблице отклонений одновременно есть липидные маркеры и иные показатели крови/биохимии.
    Нужно для шапки отчёта: не показывать «только липидный профиль», если на бланке уже смесь блоков.
    """
    if not rows:
        return False
    parts: List[str] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        parts.append(str(r.get("marker") or ""))
        parts.append(str(r.get("name") or ""))
        parts.append(str(r.get("group") or ""))
    blob = " ".join(parts).lower()
    lipid = any(
        x in blob
        for x in (
            "лпнп",
            "ldl",
            "hdl",
            "лпвп",
            "триглицер",
            "холестерин",
            "cholesterol",
            "липид",
            "apo",
            "апоб",
            "аполипопротеин",
            "липопротеин",
            "non-hdl",
            "non hdl",
        )
    )
    nonlipid = any(
        x in blob
        for x in (
            "гемоглобин",
            "гематокрит",
            "эритроцит",
            "лейкоцит",
            "тромбоцит",
            "витамин d",
            "25-oh",
            "25(oh)",
            "ферритин",
            "глюкоз",
            "креатинин",
            "мочевин",
            "соэ",
            "с-реактивн",
            "crp",
        )
    )
    return bool(lipid and nonlipid)


def _ensure_multipanel_blood_label_on_legacy(legacy: Dict[str, Any]) -> None:
    """
    document_summary.combined_oak_lipid_panel — флаг для человекочитаемой подписи типа анализа
    (pretty_physician_report_tables._friendly_doc_type_label), не только для ОАК+липиды.
    """
    if not legacy:
        return
    dt = str(legacy.get("doc_type") or legacy.get("document_type") or "").lower()
    if "lipid" not in dt and "biochemistry" not in dt:
        return
    rows = list(legacy.get("abnormal_markers_table") or legacy.get("abnormal_findings") or [])
    if not _abnormal_rows_lipid_and_nonlipid_blood(rows):
        return
    ds = dict(legacy.get("document_summary") or {})
    ds["combined_oak_lipid_panel"] = True
    legacy["document_summary"] = ds


def _cbc_to_abnormal_row(v: CbcLabValue) -> Dict[str, Any] | None:
    if v.status == "normal" or not str(v.status or "").strip():
        return None
    low_side = (
        "low" in v.status
        or v.status in ("borderline_low", "significant_low")
        or v.status == "critical"
        and v.ref_low is not None
        and v.value < v.ref_low
    )
    high_side = "high" in v.status or v.status in ("borderline_high", "significant_high")
    if v.status == "critical" and not low_side:
        high_side = True
    direction = "low" if low_side else "high" if high_side else "normal"
    if direction == "normal":
        return None
    label = cbc_label_ru(v.marker)
    val = str(v.value)
    if getattr(v, "unit", None):
        val = f"{val} {v.unit}"
    return {
        "marker": label,
        "name": label,
        "marker_code": v.marker,
        "value": val,
        "ref_low": str(v.ref_low) if v.ref_low is not None else "",
        "ref_high": str(v.ref_high) if v.ref_high is not None else "",
        "direction": direction,
        "comment": (v.clinical_note or "").strip(),
    }


def _extract_ferritin_vitamin_d_rows(text: str) -> List[Dict[str, Any]]:
    """Простые regex по общему тексту бланка (pipeline липидов их не извлекает)."""
    rows: List[Dict[str, Any]] = []
    low = (text or "").lower()
    # Ферритин: на бланках часто «Ферритин» и через блок «Концентрация N мкг/л»
    m = re.search(
        r"ферритин[\s\S]{0,450}?концентрация\s+(\d+[,.]\d+|\d+)\s*(мкг/л|µg/l|mcg/l|нг/мл|ng/ml)?",
        low,
    )
    if not m:
        m = re.search(
            r"ферритин[:\s]+(\d+[,.]?\d*)\s*(?:нг/мл|ng/ml|мкг/л|µg/l|mcg/l)?",
            low,
        )
    if m:
        try:
            val = float(m.group(1).replace(",", "."))
        except ValueError:
            val = None
        if val is not None:
            try:
                unit_raw = (m.group(2) or "").lower()
            except IndexError:
                unit_raw = ""
            unit_disp = (
                "мкг/л"
                if ("мкг" in unit_raw or "ug" in unit_raw or "mcg" in unit_raw)
                else "нг/мл"
            )
            # Клинический ориентир низких запасов (мкг/л ≈ нг/мл для ферритина)
            ref_lo, ref_hi = 15.0, 400.0
            direction = "low" if val < ref_lo else "high" if val > ref_hi else "normal"
            if direction != "normal":
                rows.append(
                    {
                        "marker": "Ферритин",
                        "value": f"{val} {unit_disp}",
                        "ref_low": str(ref_lo),
                        "ref_high": str(ref_hi),
                        "direction": direction,
                        "comment": (
                            "Низкий запас железа (ориентир <15 мкг/л); на фоне сниженного Hb — до оценки врача; "
                            "референс лаборатории может быть шире (напр. 7–140 мкг/л)."
                            if direction == "low"
                            else ""
                        ),
                    }
                )
    # 25-OH витамин D — брать «Концентрацию» из блока, не «25» из «25-гидрокси»
    vvd: Optional[float] = None
    mv = re.search(
        r"(?:витамин\s*d\s*,\s*25[-‑]\s*гидрокси|25[-‑]\s*гидрокси|кальциферол|25\s*\(?oh\)?\s*витамин\s*d)",
        low,
    )
    if mv:
        chunk = low[mv.start() : mv.start() + 700]
        mc = re.search(r"концентрация\s+(\d+[,.]\d+|\d+)\s*нг/мл", chunk)
        if mc:
            try:
                vvd = float(mc.group(1).replace(",", "."))
            except ValueError:
                vvd = None
    if vvd is None:
        mc2 = re.search(
            r"витамин\s*d\s*,\s*25[-‑]\s*гидрокси[\s\S]{0,500}?концентрация\s+(\d+[,.]\d+|\d+)\s*нг/мл",
            low,
        )
        if mc2:
            try:
                vvd = float(mc2.group(1).replace(",", "."))
            except ValueError:
                vvd = None
    if vvd is not None and 5 < vvd < 200:
        ref_lo, ref_hi = 30.0, 100.0
        direction = "low" if vvd < ref_lo else "high" if vvd > ref_hi else "normal"
        if direction != "normal":
            com = (
                "Чуть ниже нижней границы референса лаборатории (30 нг/мл); по комментарию многих лаб: 20–30 — недостаточность."
                if 20 <= vvd < 30
                else "Недостаточность/дефицит по общим целевым уровням (уточнить единицами и референсом лаборатории)."
            )
            if direction == "low":
                rows.append(
                    {
                        "marker": "25-OH витамин D",
                        "value": f"{vvd} нг/мл",
                        "ref_low": str(ref_lo),
                        "ref_high": str(ref_hi),
                        "direction": direction,
                        "comment": com,
                    }
                )
    return rows


def _legacy_has_pattern_driven_clinical_layer(legacy: Dict[str, Any]) -> bool:
    """
    P1/P2 + summary_builder: единственный источник краткого вывода для UI.
    Пока True — не подмешиваем сырой multipanel-текст и служебные вступления.
    """
    if (legacy.get("pattern_main_conclusion") or "").strip():
        return True
    cp = legacy.get("clinical_patterns") or []
    return bool(cp)


def _strip_multipanel_subtitle_suffix(legacy: Dict[str, Any]) -> None:
    suf = "Мультиблоковый бланк (липиды + др. показатели по тексту)"
    rs = str(legacy.get("report_subtitle") or "")
    if suf in rs:
        legacy["report_subtitle"] = rs.replace("· " + suf, "").replace(suf, "").strip(" ·").strip()


def _cbc_takes_priority_over_biochem_lipid_branch(extracted: str, report_type: str) -> bool:
    """
    ОАК не должен уходить в ветку липидов/биохимии только из‑за ≥3 «биохимических» подстрок в длинном бланке
    (реклама других профилей, колонтитулы и т.п.).
    """
    if report_type in ("cbc", "cbc_with_reticulocytes"):
        return True
    cm = classify_by_cbc_markers(extracted)
    if cm in ("cbc", "cbc_with_reticulocytes"):
        return True
    try:
        from app.services.clinical_engine.material_protocols.blood_protocol import detect_cbc

        vals = extract_cbc_values(extracted)
        ok, _ = detect_cbc(extracted, vals)
        return bool(ok)
    except Exception:
        return False


def _legacy_primary_is_lipid_or_biochemistry(legacy: Dict[str, Any]) -> bool:
    dt = str(legacy.get("doc_type") or legacy.get("document_type") or "").lower()
    return "lipid" in dt or "biochemistry" in dt


def _apply_combined_oak_lipid_document_summary(legacy: Dict[str, Any], extracted: str) -> None:
    """
    Шапка отчёта: мультиблок ОАК + липиды не должен отображаться как «только липидный профиль».
    """
    if not legacy or not (extracted or "").strip():
        return
    if not _legacy_primary_is_lipid_or_biochemistry(legacy):
        return
    try:
        from app.services.clinical_engine.material_protocols.material_router import _oak_form_title_primary
    except Exception:
        return
    if not _oak_form_title_primary(extracted):
        return
    ds = dict(legacy.get("document_summary") or {})
    ds["combined_oak_lipid_panel"] = True
    legacy["document_summary"] = ds


def _strip_multipanel_notice_from_summary_lines(legacy: Dict[str, Any]) -> None:
    notice = "В одном файле объединены"
    summ = list(legacy.get("summary") or [])
    if not summ:
        return
    filtered = [s for s in summ if notice not in str(s)]
    if filtered:
        legacy["summary"] = filtered


def _filter_hypotheses_lipid_marker_noise(hypos: List[Any]) -> List[Any]:
    """Убираем маркерный «мусор» из гипотез, когда основной вывод уже pattern-driven (P1)."""
    bad_sub = (
        "снижен ldl",
        "хороший уровень hdl",
        "хороший hdl",
        "ldl low",
        "good hdl",
    )
    out: List[Any] = []
    for h in hypos:
        if not isinstance(h, dict):
            out.append(h)
            continue
        hyp = str(h.get("hypothesis") or "").lower()
        if any(b in hyp for b in bad_sub):
            continue
        out.append(h)
    return out


def apply_clinical_pattern_layer_to_legacy_report(
    legacy: Dict[str, Any],
    extracted: str,
    patient_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Если отчёт собран старым lipid_engine/CBC без canonical pipeline, всё равно
    строим P1/P2 по полному тексту: extract → BIOCHEMISTRY_BLOOD + lipid_panel (без classifier),
    иначе мультиблоковый PDF с ОАК часто даёт только «Снижен LDL» в выводе.

    Для отчётов, где основной тип — ОАК (cbc / cbc_with_reticulocytes), слой не применяем:
    иначе ложные совпадения extract_blood_biochemistry перезаписывают вывод «липидными» P1/P2.
    """
    if _legacy_has_pattern_driven_clinical_layer(legacy):
        return legacy
    if not (extracted or "").strip():
        return legacy
    dt0 = str(legacy.get("doc_type") or legacy.get("document_type") or "").lower()
    if dt0 in ("cbc", "cbc_with_reticulocytes"):
        return legacy
    try:
        from app.services.clinical_engine.contracts import DocumentType
        from app.services.clinical_engine.extractor import extract_blood_biochemistry
        from app.services.clinical_engine.pipeline import report_model_to_clinical_core
        from app.services.clinical_engine.report_builder import build_report_from_values
        from app.services.clinical_engine.router import get_profile
    except Exception:
        return legacy

    values = extract_blood_biochemistry(extracted)
    if len(values) < 3:
        return legacy
    values_list = list(values)
    doc_type = DocumentType.BIOCHEMISTRY_BLOOD
    profile = get_profile(doc_type, values_list)
    if profile not in ("lipid_panel", "biochemistry_blood"):
        lipid_codes = {"total_cholesterol", "ldl_cholesterol", "hdl_cholesterol", "triglycerides"}
        profile = "lipid_panel" if lipid_codes & {v.code for v in values_list} else "biochemistry_blood"
    try:
        model = build_report_from_values(doc_type, profile, values_list)
        core = report_model_to_clinical_core(
            model,
            extracted_text=extracted,
            patient_meta=patient_meta or {},
        )
    except Exception:
        return legacy

    cpats = list(getattr(core, "clinical_patterns", None) or [])
    pm = (getattr(core, "pattern_main_conclusion", None) or "").strip()
    if not cpats and not pm:
        return legacy

    legacy["clinical_patterns"] = [p.model_dump() for p in cpats]
    legacy["pattern_summary_headline"] = (getattr(core, "pattern_summary_headline", None) or "").strip()
    legacy["pattern_main_conclusion"] = pm
    legacy["pattern_attention_items"] = [
        str(x).strip() for x in (getattr(core, "pattern_attention_items", None) or []) if str(x).strip()
    ]
    legacy["pattern_next_steps_items"] = [
        str(x).strip() for x in (getattr(core, "pattern_next_steps_items", None) or []) if str(x).strip()
    ]

    if pm:
        legacy["summary"] = [pm]
    else:
        _strip_multipanel_notice_from_summary_lines(legacy)

    legacy["interpretation"] = list(legacy.get("summary") or [])
    _strip_multipanel_subtitle_suffix(legacy)

    has_p1 = any(getattr(p, "level", None) == "P1" for p in cpats)
    if has_p1 and pm:
        legacy["top_hypotheses_table"] = _filter_hypotheses_lipid_marker_noise(
            legacy.get("top_hypotheses_table") or []
        )

    return legacy


def _merge_multipanel_laboratory_into_legacy(legacy: Dict[str, Any], extracted: str) -> Dict[str, Any]:
    """
    Pipeline биохимии часто сводится к lipid_panel и не видит ОАК/ферритин/вит. D в том же PDF.
    Дополняем legacy-отчёт извлечёнными из текста показателями и клиническими связками.
    """
    if not extracted or not legacy:
        return legacy

    existing = list(legacy.get("abnormal_markers_table") or legacy.get("abnormal_findings") or [])
    seen = {_abnormal_row_key(x) for x in existing if isinstance(x, dict)}
    merged: List[Dict[str, Any]] = [x for x in existing if isinstance(x, dict)]

    for v in extract_cbc_values(extracted):
        row = _cbc_to_abnormal_row(v)
        if not row:
            continue
        k = _abnormal_row_key(row)
        if k and k not in seen:
            seen.add(k)
            merged.append(row)

    for row in _extract_ferritin_vitamin_d_rows(extracted):
        k = _abnormal_row_key(row)
        if k and k not in seen:
            seen.add(k)
            merged.append(row)

    if len(merged) <= len(existing):
        # Уже полная таблица (pipeline извлёк Hb/липиды/вит. D) — флаг «не только липиды» без новых строк merge
        _ensure_multipanel_blood_label_on_legacy(legacy)
        return legacy

    legacy = dict(legacy)
    legacy["abnormal_findings"] = merged
    legacy["abnormal_markers_table"] = merged

    # Группы интерпретации: если в исходном отчёте пусто или только липиды — добавить блоки
    grouped = list(legacy.get("grouped_interpretation_table") or [])
    has_cbc = any("гемоглобин" in _abnormal_row_key(r) or "соэ" in _abnormal_row_key(r) for r in merged)
    has_fe = "ферритин" in "".join(_abnormal_row_key(r) for r in merged)
    hb_low = any(
        _abnormal_row_key(r) == "гемоглобин" and r.get("direction") == "low" for r in merged
    )
    ferr_low = has_fe and any(r.get("marker", "").lower().startswith("ферритин") and r.get("direction") == "low" for r in merged)

    new_groups: List[Dict[str, Any]] = []
    if has_cbc or has_fe:
        markers_fe = []
        interp_fe = "Сочетание показателей крови и железа требует клинической оценки; дефицит железа не ставится только по бланку."
        if hb_low and ferr_low:
            interp_fe = (
                "Сочетание сниженного гемоглобина и низкого ферритина соответствует картине дефицита железа "
                "(подтверждение и причина — по врачу, дообследование)."
            )
        elif hb_low:
            interp_fe = "Снижение гемоглобина — показатель для очной оценки (возможны разные причины)."
        elif ferr_low:
            interp_fe = "Низкий ферритин — сигнал к оценке запасов железа и питания; интерпретация с возрастом и клиникой."
        if hb_low or ferr_low:
            markers_fe = ["Гемоглобин", "Ферритин"] if (hb_low and ferr_low) else (["Гемоглобин"] if hb_low else ["Ферритин"])
        if markers_fe:
            new_groups.append({"group": "Железо и эритропоэз (по бланку)", "markers": markers_fe, "interpretation": interp_fe})

    if any("витамин d" in _abnormal_row_key(r) for r in merged):
        new_groups.append(
            {
                "group": "Витамин D",
                "markers": ["25-OH витамин D"],
                "interpretation": "Уровень ниже часто используемых целевых значений; коррекция и цели — по врачу и референсу лаборатории.",
            }
        )

    if new_groups:
        legacy["grouped_interpretation_table"] = grouped + new_groups

    # Гипотезы и шаги
    hypos = list(legacy.get("top_hypotheses_table") or [])
    hypo_texts = {
        str(h.get("hypothesis", "")).lower()
        for h in hypos
        if isinstance(h, dict)
    }
    if hb_low and ferr_low and not any("железодефицит" in t for t in hypo_texts):
        hypos.insert(
            0,
            {
                "hypothesis": "Железодефицитное состояние (по сочетанию Hb и ферритина) — рабочая гипотеза, не диагноз.",
                "basis": "Снижение гемоглобина и низкий ферритин в одном документе.",
                "comment": "Требуется клиническая корреляция, питание, исключение кровопотерь и воспаления.",
            },
        )
    follow = list(legacy.get("recommended_followup_table") or [])
    ferritin_on_blank = bool(
        re.search(r"ферритин[\s\S]{0,450}?концентрация\s+[\d,.]+", extracted, re.IGNORECASE)
        or re.search(r"ферритин[:\s]+[\d,.]+\s*(?:мкг|нг|ng|mcg)", extracted, re.IGNORECASE)
    )
    if (hb_low or ferr_low) and not any("ферритин" in str(f.get("check", "")).lower() for f in follow):
        if ferritin_on_blank:
            follow.insert(
                0,
                {
                    "direction": "Терапевт / гематолог",
                    "check": (
                        "ОАК в динамике; насыщение трансферрина, ОЖСС при необходимости; "
                        "корреляция с питанием (ферритин уже указан на бланке)"
                    ),
                    "why": "Снижение Hb и/или низкий ферритин — клиническая оценка без дублирования уже выполненного ферритина",
                    "priority": "Высокий" if hb_low and ferr_low else "Средний",
                },
            )
        else:
            follow.insert(
                0,
                {
                    "direction": "Терапевт / гематолог",
                    "check": "Оценка железа: ферритин, ОАК в динамике, при необходимости насыщение трансферрина",
                    "why": "Уточнение причины изменений Hb/ферритина",
                    "priority": "Высокий" if hb_low and ferr_low else "Средний",
                },
            )
    if hypos != legacy.get("top_hypotheses_table"):
        legacy["top_hypotheses_table"] = hypos
    if follow != legacy.get("recommended_followup_table"):
        legacy["recommended_followup_table"] = follow

    summ = list(legacy.get("summary") or [])
    # Не перебиваем интегрированный P1/P2 summary вводным абзацем.
    # Текст про «липидный модуль» — только если исходный отчёт действительно из липид/биохим ветки.
    if not _legacy_has_pattern_driven_clinical_layer(legacy) and _legacy_primary_is_lipid_or_biochemistry(legacy):
        notice = (
            "В одном файле объединены несколько лабораторных блоков; ниже учтены липидный модуль системы "
            "и дополнительно извлечённые из текста показатели (ОАК, ферритин, витамин D — при наличии в бланке)."
        )
        if summ and notice not in str(summ[0]):
            legacy["summary"] = [notice] + summ
        elif not summ:
            legacy["summary"] = [notice]

    _rs = str(legacy.get("report_subtitle") or "").strip()
    if not _legacy_has_pattern_driven_clinical_layer(legacy) and _legacy_primary_is_lipid_or_biochemistry(legacy):
        _suffix = "Мультиблоковый бланк (липиды + др. показатели по тексту)"
        legacy["report_subtitle"] = f"{_rs} · {_suffix}" if _rs else _suffix

    _ensure_multipanel_blood_label_on_legacy(legacy)

    return legacy


def _finalize_laboratory_physician_report(
    report: Dict[str, Any],
    extracted: str,
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """После lipid_engine / CBC: подмешать ОАК·ферритин·вит. D, затем P1/P2 слой по полному тексту."""
    merged = _merge_multipanel_laboratory_into_legacy(report, extracted)
    _apply_combined_oak_lipid_document_summary(merged, extracted)
    enrich_report_with_patient_demographics(merged, extracted, profile)
    patient_meta = _patient_meta_from_report_and_profile(merged, profile)
    merged = apply_clinical_pattern_layer_to_legacy_report(merged, extracted, patient_meta)
    merged["professional_summary"] = _build_plain_text_report(merged)
    return merged


def _patient_meta_from_profile(profile: Dict[str, Any] | None) -> Dict[str, Any]:
    """Для P1/P2 pediatric adjustments и др."""
    if not profile:
        return {}
    out: Dict[str, Any] = {}
    age = profile.get("age_years") or profile.get("age")
    if age is not None:
        try:
            out["age_years"] = float(age)
        except (TypeError, ValueError):
            pass
    sex = profile.get("sex") or profile.get("gender")
    if sex:
        out["sex"] = str(sex)
    by = profile.get("birth_year")
    if by is not None:
        try:
            out["birth_year"] = int(float(by))
        except (TypeError, ValueError):
            pass
    return out


def _patient_meta_from_report_and_profile(
    report: Dict[str, Any],
    profile: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Объединяет meta из профиля и заполненного patient (после enrich из текста бланка)."""
    meta = _patient_meta_from_profile(profile)
    p = report.get("patient") or {}
    if p.get("age_years") is not None:
        try:
            meta["age_years"] = float(p["age_years"])
        except (TypeError, ValueError):
            pass
    if p.get("sex"):
        meta["sex"] = p["sex"]
    if p.get("birth_year") is not None:
        try:
            meta["birth_year"] = int(p["birth_year"])
        except (TypeError, ValueError):
            pass
    return meta


def _attach_material_routing(report: Dict[str, Any], extracted_text: str) -> Dict[str, Any]:
    """Добавляет material-first метаданные к отчёту (аудит маршрутизации)."""
    if not report:
        return report
    try:
        routed = route_document(extracted_text)
        report["material"] = routed.material.value
        report["material_confidence"] = routed.material_confidence
        report["material_routing"] = routed.model_dump()
    except Exception:
        pass
    return report


def _ensure_list(value: Any) -> List[str]:
    """Нормализация в список строк для безопасного join (как в pretty_physician_report_tables)."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(value).strip()] if str(value).strip() else []


def _fmt_marker_line(item: Dict[str, Any]) -> str:
    marker = item.get("marker", item.get("name", ""))
    value = item.get("value", "")
    ref_low = item.get("ref_low", "")
    ref_high = item.get("ref_high", "")
    direction = item.get("direction", item.get("flag", ""))
    arrow = "↑" if str(direction).lower() == "high" else "↓" if str(direction).lower() == "low" else ""
    comment = item.get("comment") or item.get("note") or ""
    base = f"- {marker} {value} {arrow} ({ref_low}–{ref_high})".strip()
    if comment:
        base += f" — {comment}"
    return base


def _interpretation_as_lines(report: Dict[str, Any]) -> List[str]:
    pm = str(report.get("pattern_main_conclusion") or "").strip()
    if pm:
        if "\n" in pm:
            return [ln.strip() for ln in pm.split("\n") if ln.strip()]
        return [pm]
    interp = report.get("interpretation")
    if isinstance(interp, list) and interp:
        return [str(x) for x in interp if x and str(x).strip()]
    summ = report.get("summary")
    if isinstance(summ, list) and summ:
        return [str(x) for x in summ if x and str(x).strip()]
    if isinstance(summ, str) and summ.strip():
        return [summ.strip()]
    return []


def _build_plain_text_report(report: Dict[str, Any]) -> str:
    patient = report.get("patient") or report.get("document_summary") or {}
    abnormal = report.get("abnormal_findings") or report.get("abnormal_markers_table") or []
    interpretation = _interpretation_as_lines(report)
    follow_up = report.get("follow_up") or {}
    follow_table = report.get("recommended_followup_table") or []
    limitations = report.get("limitations") or []
    grouped = report.get("grouped_interpretation_table") or []
    hypos = report.get("top_hypotheses_table") or []

    parts: List[str] = []
    parts.append("Отчёт для врача")
    parts.append("")
    parts.append("Документ и пациент:")
    doc_type = report.get("document_type", report.get("doc_type", "—"))
    parts.append(f"- Тип документа: {doc_type}")
    parts.append(f"- Пол: {patient.get('sex', '—')}")
    parts.append(f"- Возраст: {patient.get('age_years', '—')}")
    parts.append(f"- Биоматериал: {patient.get('sample_type', '—')}")
    parts.append(f"- Дата взятия: {patient.get('collection_date', '—')}")
    parts.append(f"- Дата выполнения: {patient.get('report_date', '—')}")
    parts.append("")

    parts.append("Ключевые отклонения:")
    if abnormal:
        for f in abnormal[:15]:
            parts.append(_fmt_marker_line(f))
    else:
        # При наличии данных (биохимия/липиды) запрещено писать «нет отклонений»
        msg = report.get("no_deviations_placeholder")
        if msg:
            parts.append(f"- {msg}")
        else:
            parts.append("- Существенных отклонений для отображения не найдено.")
    parts.append("")

    risk = report.get("risk_assessment")
    if risk and isinstance(risk, dict):
        summary_text = risk.get("summary_text", "").strip()
        if summary_text:
            parts.append("Оценка риска:")
            parts.append(summary_text)
            domain_risks = risk.get("domain_risks") or []
            primary = next((d for d in domain_risks if d.get("domain") == risk.get("primary_domain")), None)
            if primary and primary.get("rationale"):
                for r in primary.get("rationale", [])[:5]:
                    if r:
                        parts.append(f"- {r}")
            parts.append("")

    if grouped:
        parts.append("Клиническая интерпретация по группам:")
        for g in grouped[:8]:
            group_name = g.get("group", "—")
            markers = ", ".join(_ensure_list(g.get("markers"))) or "—"
            interp = g.get("interpretation", "—")
            parts.append(f"- {group_name}: {markers}. {interp}")
        parts.append("")

    if hypos:
        parts.append("Рабочие гипотезы:")
        for h in hypos[:5]:
            if isinstance(h, dict):
                label = str(h.get("hypothesis") or "—").strip()
                basis = str(h.get("basis") or "").strip()
                comment = str(h.get("comment") or "").strip()
                line = f"- {label}"
                if basis:
                    line += f" | основание: {basis}"
                if comment:
                    line += f" | {comment}"
                parts.append(line)
            else:
                parts.append(f"- {str(h).strip()}")
        parts.append("")

    parts.append("Краткий вывод:")
    if interpretation:
        for line in interpretation[:6]:
            s = str(line or "").strip()
            if s:
                parts.append(f"- {s}")
    else:
        parts.append("- Изолированно не устанавливает диагноз.")
    parts.append("")

    parts.append("Что проверить дальше:")
    if follow_table:
        for row in follow_table[:8]:
            parts.append(
                f"- {row.get('direction', '—')}: {row.get('check', '—')} "
                f"(зачем: {row.get('why', '—')}; приоритет: {row.get('priority', '—')})"
            )
    else:
        tests = follow_up.get("tests") or []
        referrals = follow_up.get("referrals") or []
        notes = follow_up.get("notes") or []
        merged = list(tests) + list(referrals) + list(notes)
        if merged:
            for x in merged[:8]:
                s = str(x or "").strip()
                if s:
                    parts.append(f"- {s}")
        else:
            parts.append("- Очная клиническая интерпретация.")
    parts.append("")

    parts.append("Ограничения:")
    if limitations:
        for x in limitations[:8]:
            if isinstance(x, dict):
                parts.append(f"- {x.get('limitation', '—')}: {x.get('value', '—')}")
            else:
                s = str(x or "").strip()
                if s:
                    parts.append(f"- {s}")
    else:
        parts.append("- Результатов исследования недостаточно для постановки диагноза.")

    return "\n".join(parts).strip()


def format_document_physician_report(report: Dict[str, Any]) -> str:
    """
    Возвращает только plain text версию physician report.
    Никогда не возвращает HTML.
    """
    if report.get("professional_summary") and "<html" not in str(report.get("professional_summary", "")).lower():
        return str(report["professional_summary"]).strip()
    return _build_plain_text_report(report)


def _build_generic_lab_physician_report(
    doc: Dict[str, Any],
    extracted: str,
    *,
    biochem_markers_count: int = 0,
    numeric_values_count: int = 0,
) -> Dict[str, Any]:
    """
    Fallback для лабораторных документов без точного профиля.
    Если из текста удаётся извлечь показатели (например ОАК) — показываем их и минимальную оценку,
    без формулировки «это не органические кислоты» как главного сообщения.
    При наличии данных (>=3 маркеров биохимии или >=5 числовых показателей) запрещено писать
    «нет отклонений» / «нет гипотез» — только «обнаружены показатели; требуется оценка врача».
    """
    filename = doc.get("filename") or "документ"
    has_enough_data = biochem_markers_count >= 3 or numeric_values_count >= 5
    # Пытаемся извлечь хотя бы CBC-маркеры для любого лабораторного текста
    cbc_values = extract_cbc_values(extracted)
    abnormal = []
    if cbc_values:
        for v in cbc_values:
            if v.status not in ("normal", ""):
                abnormal.append({
                    "marker": v.marker,
                    "value": str(v.value),
                    "ref_low": str(v.ref_low) if v.ref_low is not None else "",
                    "ref_high": str(v.ref_high) if v.ref_high is not None else "",
                    "direction": "high" if v.status in ("high", "borderline_high", "critical") else "low",
                    "comment": v.clinical_note or "",
                })
    lines = [s.strip() for s in extracted.splitlines() if s.strip()][:12]
    summary_preview = " ".join(lines)[:400].strip()
    if len(summary_preview) < 30:
        summary_preview = "Текст из документа извлечён; для интерпретации покажите анализ врачу."

    if cbc_values:
        summary_lines = [
            "Лабораторный документ. Извлечены показатели (см. ниже).",
            "Для полной интерпретации и плана дообследования покажите анализ врачу.",
        ]
        if abnormal:
            summary_lines.append("Обнаружены отклонения от референса — требуется клиническая оценка.")
        summary_lines.append(summary_preview[:280] + ("…" if len(summary_preview) > 280 else ""))
        professional = (
            f"Тип документа: лабораторный результат (общий). Файл: {filename}.\n\n"
            f"Извлечённые показатели: {len(cbc_values)}. Отклонения: {len(abnormal)}.\n"
            f"Для клинической интерпретации и рекомендаций покажите анализ врачу."
        )
        hypotheses = [{"hypothesis": "Требует клинической оценки извлечённых показателей.", "basis": "", "comment": ""}] if abnormal else []
        followup = [{"direction": "Лаборатория", "check": "Повторная консультация / контроль по назначению врача.", "why": "Уточнение картины", "priority": "Средний"}] if abnormal else []
    else:
        summary_lines = [
            "Документ загружен. Точный тип анализа не определён.",
            "Для интерпретации покажите оригинал врачу или загрузите отчёт ОАК, липиды, органические кислоты в моче.",
            summary_preview[:280] + ("…" if len(summary_preview) > 280 else ""),
        ]
        professional = (
            f"Тип документа: лабораторный результат (общий). Файл: {filename}.\n"
            f"Текст извлечён; для клинической интерпретации покажите анализ врачу."
        )
        hypotheses = []
        followup = []

    # Запрет fallback-формулировок при наличии данных: не писать «нет отклонений» / «нет гипотез»
    if has_enough_data and not cbc_values:
        summary_lines = [
            "Обнаружены лабораторные показатели (биохимия/липиды и др.).",
            "Для интерпретации и плана дообследования покажите анализ врачу.",
            summary_preview[:280] + ("…" if len(summary_preview) > 280 else ""),
        ]
        hypotheses = [{"hypothesis": "Требует клинической оценки показателей.", "basis": "Данные извлечены из документа", "comment": ""}]
        followup = [{"direction": "Врач", "check": "Интерпретация липидов/биохимии и при необходимости дообследование.", "why": "Оценка рисков", "priority": "Средний"}]
    elif has_enough_data and cbc_values and not abnormal:
        summary_lines = [
            "Лабораторный документ. Извлечены показатели (см. ниже).",
            "Для полной интерпретации и плана дообследования покажите анализ врачу.",
            summary_preview[:280] + ("…" if len(summary_preview) > 280 else ""),
        ]
        hypotheses = [{"hypothesis": "Требует клинической оценки извлечённых показателей.", "basis": "", "comment": ""}]

    no_deviations_placeholder = (
        "Обнаружены лабораторные показатели; для интерпретации требуется оценка врача."
        if has_enough_data
        else None
    )
    return {
        "doc_type": "generic_lab_document",
        "document_type": "generic_lab_document",
        "document_name": filename,
        "document_summary": {},
        "patient": {},
        "summary": summary_lines,
        "abnormal_findings": abnormal,
        "abnormal_markers_table": abnormal,
        "recommended_followup_table": followup,
        "top_hypotheses_table": hypotheses,
        "no_deviations_placeholder": no_deviations_placeholder,
        "grouped_interpretation_table": [],
        "interpretation": summary_lines[:2],
        "follow_up": {"tests": [f["check"] for f in followup], "referrals": [], "notes": []},
        "limitations": ["Интерпретация не заменяет очную оценку врача."],
        "professional_summary": professional,
    }


def build_document_physician_report(
    doc: Dict[str, Any],
    profile: Dict[str, Any] | None = None,
    raw_hypotheses: List[str] | None = None,
) -> Dict[str, Any] | None:
    """
    Строит документ-ориентированный physician report.
    Определяет тип анализа и использует соответствующий движок:
    - organic_acids → organic acids pipeline
    - lipid_panel → lipid_engine
    - остальные → generic fallback
    """
    extracted = (doc.get("extracted_text") or "").strip()
    if not extracted:
        return None

    # 1. Новый clinical engine: biochemistry_blood / lipid_panel по canonical pipeline
    #    (classifier → extractor → router → rules → report_builder). Приоритет над organic_acids.
    try:
        model = run_blood_biochemistry_pipeline(extracted)
        if model is not None:
            legacy = report_model_to_legacy_dict(
                model,
                doc.get("filename") or "",
                extracted_text=extracted,
                patient_meta=_patient_meta_from_profile(profile),
            )
            legacy = _merge_multipanel_laboratory_into_legacy(legacy, extracted)
            _apply_combined_oak_lipid_document_summary(legacy, extracted)
            enrich_report_with_patient_demographics(legacy, extracted, profile)
            patient_meta = _patient_meta_from_report_and_profile(legacy, profile)
            legacy = apply_clinical_pattern_layer_to_legacy_report(
                legacy, extracted, patient_meta
            )
            legacy["professional_summary"] = _build_plain_text_report(legacy)
            return _attach_material_routing(legacy, extracted)
    except Exception:
        pass

    # Определяем тип анализа: сначала по фразам, при unknown — по числу извлечённых CBC-маркеров (>= 6)
    report_type = detect_report_type(extracted)
    if report_type == "unknown":
        report_type = classify_by_cbc_markers(extracted) or report_type

    doc_fn = (doc.get("filename") or "").strip()
    biochem_markers_count = _count_biochem_matches(extracted)

    # Органические кислоты — до ОАМ: эвристика «моча»/лейкоциты часто даёт urinalysis раньше, чем сработает ОК.
    if biochem_markers_count < 3 and (
        report_type == "organic_acids"
        or route_organic_acids(extracted)
        or filename_suggests_organic_acids(doc_fn)
    ):
        report = build_organic_acids_report(
            doc=doc,
            profile=profile,
            raw_hypotheses=raw_hypotheses,
        )
        if report:
            report["professional_summary"] = _build_plain_text_report(report)
            return _attach_material_routing(report, extracted)

    # ОАМ: до CBC, чтобы моча не интерпретировалась как кровь (в ОАМ тоже есть лейкоциты/эритроциты).
    if report_type == "urinalysis":
        report = build_urinalysis_report(extracted, doc_fn)
        if report:
            enrich_report_with_patient_demographics(report, extracted, profile)
        return _attach_material_routing(report if report else {}, extracted)

    # Жёсткая защита: при >=3 маркерах биохимии НИКОГДА не маршрутизировать в organic_acids
    # Биохимия по маркерам → пробуем липидный/биохимический отчёт, но не вместо однозначного ОАК.
    if report_type == "biochemistry" or (
        biochem_markers_count >= 3 and not _cbc_takes_priority_over_biochem_lipid_branch(extracted, report_type)
    ):
        report = build_lipid_report(
            doc=doc,
            extracted_text=extracted,
            profile=profile,
        )
        if report and (
            report.get("abnormal_findings") or report.get("top_hypotheses_table") or report.get("summary")
        ):
            report = _finalize_laboratory_physician_report(report, extracted, profile)
            return _attach_material_routing(report, extracted)

    # Старый парсер organic acids — только при явной сигнатуре и отсутствии биохимических маркеров
    if biochem_markers_count < 3 and is_organic_acids_urine_document(extracted):
        result = parse_organic_acids_urine(
            text=extracted,
            filename=doc.get("filename") or "",
            profile=profile,
        )
        if result:
            result["professional_summary"] = _build_plain_text_report(result)
        return _attach_material_routing(result, extracted) if result else result

    # Липидный профиль
    if report_type == "lipid_panel":
        report = build_lipid_report(
            doc=doc,
            extracted_text=extracted,
            profile=profile,
        )
        if report:
            report = _finalize_laboratory_physician_report(report, extracted, profile)
        return _attach_material_routing(report, extracted) if report else report

    # ОАК / CBC (в т.ч. с ретикулоцитами)
    if report_type in ("cbc", "cbc_with_reticulocytes"):
        report = build_cbc_report(
            doc=doc,
            extracted_text=extracted,
            profile=profile,
        )
        if report:
            report = _finalize_laboratory_physician_report(report, extracted, profile)
            return _attach_material_routing(report, extracted) if report else report

    # Fallback: если тип неизвестен/другой, но по тексту извлекается полноценный ОАК —
    # интерпретируем как CBC, чтобы не уходить в generic с «нет значимых отклонений».
    cbc_values = extract_cbc_values(extracted)
    if len(cbc_values) >= 4:
        report = build_cbc_report(
            doc=doc,
            extracted_text=extracted,
            profile=profile,
        )
        if report:
            # Всегда возвращаем CBC-отчёт при успешном извлечении 4+ маркеров (это уже ОАК).
            report = _finalize_laboratory_physician_report(report, extracted, profile)
            return _attach_material_routing(report, extracted)

    # Запрет generic fallback при биохимии: при >=3 маркерах биохимии ещё раз пробуем липидный отчёт.
    # Если получили отчёт (даже без сильных находок) — возвращаем его, без «нет отклонений».
    if biochem_markers_count >= 3 and not _cbc_takes_priority_over_biochem_lipid_branch(extracted, report_type):
        report = build_lipid_report(
            doc=doc,
            extracted_text=extracted,
            profile=profile,
        )
        if report:
            if not (report.get("abnormal_findings") or report.get("top_hypotheses_table")) and not report.get("summary"):
                report["summary"] = [
                    "Обнаружены показатели биохимии крови.",
                    "Для интерпретации и плана дообследования покажите анализ врачу.",
                ]
            report = _finalize_laboratory_physician_report(report, extracted, profile)
            return _attach_material_routing(report, extracted)

    # Прочие лабораторные документы (ОАК, биохимия, общий результат и т.д.):
    # возвращаем минимальный отчёт по извлечённому тексту, чтобы не показывать
    # «загрузите повторно», а дать пользователю увидеть, что документ принят.
    generic = _build_generic_lab_physician_report(
        doc=doc,
        extracted=extracted,
        biochem_markers_count=biochem_markers_count,
        numeric_values_count=len(cbc_values),
    )
    return _attach_material_routing(generic, extracted)
