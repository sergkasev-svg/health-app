"""
Движок интерпретации ОАК/CBC: извлечение значений, rule-based паттерны, гипотезы, рекомендации.
Не выдаёт пустые блоки при наличии отклонений.
"""
from typing import Any, Dict, List, Optional

from app.services.clinical_engine.derived_indices import (
    DerivedIndex,
    compute_derived_indices_for_document,
    format_derived_indices_section,
)
from app.services.cbc_display_labels import cbc_group_markers_ru, cbc_label_ru
from app.services.lab_value_extractor import LabValue, extract_cbc_values


# Референсы по умолчанию для интерпретации (ммоль/г/л в типичных единицах)
DEFAULT_REF = {
    "Hb": (120, 160),
    "MCH": (27, 31),
    "MCV": (80, 100),
    "Reticulocytes_abs": (50, 100),
    "Eosinophils": (0, 5),
}


def interpret_cbc(values: List[LabValue]) -> Dict[str, Any]:
    """
    Строит интерпретацию CBC по извлечённым значениям.
    Возвращает: summary, key_abnormalities, pattern_interpretation, working_hypotheses, next_tests,
    urgency_signals, limitations.
    Не возвращает пустые блоки при наличии хотя бы одного отклонения.
    """
    key_abnormalities: List[Dict[str, Any]] = []
    pattern_interpretation: List[str] = []
    working_hypotheses: List[str] = []
    next_tests: List[str] = []

    def get_val(marker: str) -> Optional[float]:
        for v in values:
            if v.marker == marker:
                return v.value
        return None

    def get_status(marker: str) -> str:
        for v in values:
            if v.marker == marker:
                return v.status
        return "normal"

    # Устанавливаем clinical_note до сборки key_abnormalities
    for v in values:
        if v.status not in ("normal", "") and not v.clinical_note:
            if v.marker == "MCH":
                v.clinical_note = "Сниженное содержание гемоглобина в эритроците."
            elif v.marker == "Reticulocytes_abs":
                v.clinical_note = "Сниженная регенераторная активность эритропоэза."
            elif "Eosinophil" in v.marker or v.marker == "Eosinophils":
                v.clinical_note = "Лёгкая относительная эозинофилия."
            elif v.marker == "MPV":
                v.clinical_note = "Средний объём тромбоцитов выше референса; при нормальном количестве PLT чаще неспецифично."
            elif v.marker == "P-LCR":
                v.clinical_note = "Доля крупных тромбоцитов слегка повышена; при нормальном PLT неспецифично."
            elif v.marker == "ESR":
                v.clinical_note = "СОЭ незначительно ускорена; изолированно не имеет самостоятельной диагностической ценности."

    # Собираем все отклонения (low, high, borderline) без дубликатов
    seen_markers = set()
    for v in values:
        if v.status not in ("normal", "") and v.marker not in seen_markers:
            seen_markers.add(v.marker)
            key_abnormalities.append(v.to_abnormality_dict())

    # Канонический список маркеров в findings — все секции строятся только из него
    markers_in_findings = {a.get("marker") for a in key_abnormalities}

    # --- Правило: низкий MCH + Hb у нижней границы + низкие ретикулоциты ---
    hb = get_val("Hb")
    mch = get_val("MCH")
    ret_abs = get_val("Reticulocytes_abs")
    ret_rel_status = get_status("Reticulocytes")
    mch_low = get_status("MCH") in ("low", "borderline_low")
    hb_low_or_border = get_status("Hb") in ("low", "borderline_low") or (hb is not None and hb < 125)
    ret_low_abs = get_status("Reticulocytes_abs") == "low" or (ret_abs is not None and ret_abs < 50)
    ret_low_rel = ret_rel_status in ("low", "borderline_low")
    # На бланках часто только ретикулоциты в % без строки abs
    ret_low = ret_low_abs or ret_low_rel

    if mch_low and (hb_low_or_border or hb is None) and (ret_low or ret_abs is None):
        pattern_interpretation.append(
            "Низкий MCH на фоне гемоглобина у нижней границы и низких ретикулоцитов может соответствовать раннему железодефициту или гипопролиферативному эритропоэзу."
        )
        if "Латентный дефицит железа" not in working_hypotheses:
            working_hypotheses.append("Латентный дефицит железа")
        if "Гипопролиферативный эритропоэз" not in working_hypotheses:
            working_hypotheses.append("Гипопролиферативный эритропоэз")
        for t in ("Ферритин", "Сывороточное железо", "Трансферрин / ОЖСС", "Насыщение трансферрина"):
            if t not in next_tests:
                next_tests.append(t)

    if mch_low and "Ферритин" not in next_tests:
        next_tests.append("Ферритин")
    if ret_low and "Ферритин" not in next_tests:
        next_tests.append("Ферритин")

    # Изолированно низкие ретикулоциты (% и/или abs) без полного триада MCH+Hb — всё равно содержательная гипотеза
    if ret_low and not (mch_low and (hb_low_or_border or hb is None)):
        if not any("ретикул" in p.lower() or "эритропоэз" in p.lower() for p in pattern_interpretation):
            pattern_interpretation.append(
                "Снижены ретикулоциты: может отражать снижение регенераторной активности эритропоэза; "
                "при нормальном гемоглобине оценивают динамику, железо (ферритин) и клинический контекст."
            )
        if not any("ретикул" in h.lower() or "гипопролифер" in h.lower() or "желез" in h.lower() for h in working_hypotheses):
            working_hypotheses.append(
                "Гипопролиферативный эритропоэз или ранний дефицит железа (по сниженным ретикулоцитам) — рабочая гипотеза, не диагноз."
            )

    # --- Правило: эозинофилы относительные повышены ---
    eos_rel = get_val("Eosinophils")
    eos_status = get_status("Eosinophils")
    if eos_status in ("high", "borderline_high") or (eos_rel is not None and eos_rel > 5):
        pattern_interpretation.append(
            "Лёгкая относительная эозинофилия требует сопоставления с аллергическим анамнезом, лекарствами и паразитарным контекстом."
        )
        if not any("эозинофил" in h.lower() or "аллерг" in h.lower() for h in working_hypotheses):
            working_hypotheses.append("Аллергический фон или иная причина лёгкой эозинофилии")
        if "IgE / паразитология по жалобам" not in next_tests:
            next_tests.append("IgE / паразитология по жалобам")

    # B12/фолат по показаниям
    if "B12 / фолат по показаниям" not in next_tests and (mch_low or ret_low):
        next_tests.append("B12 / фолат по показаниям")

    # --- Мягкие неспецифические сигналы: MPV, P-LCR, СОЭ (при нормальных Hb, WBC, PLT) ---
    plt_val = get_val("PLT")
    plt_status = get_status("PLT")
    mpv_high = get_status("MPV") in ("high", "borderline_high", "significant_high")
    pdw_high = get_status("PDW") in ("high", "borderline_high", "significant_high")
    plcr_high = get_status("P-LCR") in ("high", "borderline_high", "significant_high")
    esr_high = get_status("ESR") in ("high", "borderline_high", "significant_high")
    plt_normal = plt_status == "normal" and (plt_val is None or (150 <= plt_val <= 400))
    platelet_indices_high = mpv_high or pdw_high or plcr_high
    if (platelet_indices_high or esr_high) and plt_normal and not (mch_low or ret_low):
        if platelet_indices_high:
            idx_codes = [c for c, ok in (("MPV", mpv_high), ("PDW", pdw_high), ("P-LCR", plcr_high)) if ok]
            idx_ru = cbc_group_markers_ru(idx_codes)
            pattern_interpretation.append(
                f"Умеренно изменённые тромбоцитарные индексы ({idx_ru}) при нормальном количестве тромбоцитов "
                "чаще неспецифичны; оценка в контексте жалоб и динамики."
            )
        if esr_high:
            pattern_interpretation.append(
                "Незначительное ускорение СОЭ само по себе не позволяет сделать диагностический вывод; оценка в клиническом контексте."
            )
        if "CRP — при наличии жалоб или подозрения на воспаление" not in next_tests and "CRP" not in str(next_tests):
            next_tests.append("CRP — при наличии жалоб или подозрения на воспаление")
        if "Повтор ОАК в динамике по клинической необходимости" not in next_tests:
            next_tests.append("Повтор ОАК в динамике по клинической необходимости")

    # CRP при необходимости
    if "CRP при необходимости" not in next_tests and "CRP" not in str(next_tests):
        next_tests.append("CRP при необходимости")

    # Гипотезы только по маркерам из key_abnormalities (до fallback)
    mild_findings_only = (platelet_indices_high or esr_high) and plt_normal and not (mch_low or ret_low)
    if mild_findings_only and not any(
        "неспецифич" in h.lower() or "реактив" in h.lower() or "ускорение СОЭ" in h or "СОЭ" in h
        for h in working_hypotheses
    ):
        soft_lab_codes = ("ESR", "MPV", "PDW", "P-LCR")
        if "ESR" in markers_in_findings and not any(c in markers_in_findings for c in ("MPV", "PDW", "P-LCR")):
            working_hypotheses.append("Изолированное неспецифическое ускорение СОЭ без чёткого самостоятельного лабораторного паттерна.")
        elif any(c in markers_in_findings for c in soft_lab_codes):
            parts_ru = [cbc_label_ru(m) for m in soft_lab_codes if m in markers_in_findings]
            working_hypotheses.append(
                "ОАК без клинически значимых отклонений. Неспецифические изменения ("
                + ", ".join(parts_ru)
                + ") требуют оценки в клиническом контексте."
            )

    # Запрет пустых выводов: при наличии отклонений всегда есть хотя бы гипотеза и рекомендация
    if key_abnormalities and not working_hypotheses:
        working_hypotheses.append("Требует клинической оценки выявленных отклонений.")
    if key_abnormalities and not next_tests:
        next_tests.append("Повторная консультация / контроль по назначению врача.")

    # Summary: только по маркерам из key_abnormalities, человечный тон
    has_severe = any(
        a.get("status") in ("low", "significant_low", "high", "significant_high", "critical")
        for a in key_abnormalities
    )
    only_mild = key_abnormalities and not has_severe
    if pattern_interpretation or working_hypotheses or key_abnormalities:
        summary_parts = []
        if (only_mild or mild_findings_only) and (platelet_indices_high or esr_high):
            only_esr = "ESR" in markers_in_findings and not any(
                c in markers_in_findings for c in ("MPV", "PDW", "P-LCR")
            )
            if only_esr:
                summary_parts.append(
                    "ОАК в целом без клинически значимых отклонений. Отмечается незначительное ускорение СОЭ; "
                    "изолированно этот показатель неспецифичен и требует оценки только в клиническом контексте."
                )
            else:
                soft = []
                if "ESR" in markers_in_findings:
                    soft.append("СОЭ")
                for c in ("MPV", "PDW", "P-LCR"):
                    if c in markers_in_findings:
                        soft.append(cbc_label_ru(c))
                if soft:
                    summary_parts.append(
                        "ОАК в целом без клинически значимых отклонений. Отмечаются лишь неспецифические изменения ("
                        + ", ".join(soft)
                        + "); оценка в клиническом контексте."
                    )
                else:
                    summary_parts.append("ОАК в целом без клинически значимых отклонений. Отдельные неспецифические изменения требуют оценки в клиническом контексте.")
        if not summary_parts and working_hypotheses:
            summary_parts.append("Обнаружены признаки: " + "; ".join(working_hypotheses[:3]) + ".")
        if pattern_interpretation and not summary_parts:
            summary_parts.append(pattern_interpretation[0][:200])
        summary = " ".join(summary_parts).strip() or "Обнаружены отклонения в общем анализе крови, требующие уточнения."
    else:
        summary = "Показатели в пределах референса, существенных отклонений не выявлено."

    urgency_signals = [
        "Срочное обращение требуется не по факту единичного отклонения в бланке, а при опасных симптомах или резком ухудшении состояния (нарастающая слабость, одышка, обмороки, выраженная бледность, кровотечение)."
    ]
    limitations: List[str] = [
        "Интерпретация не заменяет очную оценку врача.",
        "Изолированные мягкие лабораторные отклонения не позволяют установить диагноз без клинических данных.",
    ]
    if mch_low or ret_low:
        limitations.append(
            "Для подтверждения дефицита железа одного ОАК недостаточно; нужен ферритин и показатели обмена железа."
        )

    # Клиническая интерпретация по группам для рендерера
    grouped_interpretation: List[Dict[str, Any]] = []
    grouped_interpretation.append({
        "group": "Эритроциты, гемоглобин",
        "markers": "Hb, RBC, Hct, MCV, MCH, MCHC",
        "interpretation": "Признаков анемии не выявлено." if not mch_low and not hb_low_or_border else "Возможен латентный дефицит железа / гипопролиферация (см. гипотезы).",
    })
    grouped_interpretation.append({
        "group": "Лейкоциты, формула",
        "markers": "WBC, нейтрофилы, лимфоциты, эозинофилы",
        "interpretation": "Признаков выраженного воспалительного сдвига по ОАК нет." if get_status("WBC") == "normal" else "Оценка лейкоцитарной формулы в контексте клиники.",
    })
    plt_idx_codes = [c for c in ("MPV", "PDW", "P-LCR") if c in markers_in_findings]
    if plt_idx_codes:
        idx_ru = cbc_group_markers_ru(plt_idx_codes)
        grouped_interpretation.append({
            "group": "Тромбоцитарные индексы",
            "markers": "Тромбоциты, " + idx_ru,
            "interpretation": (
                f"Изменения индексов ({idx_ru}) при нормальном количестве тромбоцитов чаще неспецифичны; "
                "сопоставить с жалобами и динамикой."
            ),
        })
    if "ESR" in markers_in_findings:
        grouped_interpretation.append({
            "group": "СОЭ",
            "markers": "СОЭ",
            "interpretation": "Незначительно ускорена, неспецифична вне клинического контекста.",
        })

    # --- Сценарий «только СОЭ», без других отклонений: понятная подача + действия + upsell ---
    only_esr_mild = (
        "ESR" in markers_in_findings
        and "MPV" not in markers_in_findings
        and "PDW" not in markers_in_findings
        and "P-LCR" not in markers_in_findings
        and "Eosinophils" not in markers_in_findings
        and not mch_low
        and not ret_low
    )
    patient_friendly: Dict[str, Any] = {}
    upsell_cta: Dict[str, Any] = {}
    if only_esr_mild and esr_high:
        patient_friendly = {
            "what_happened": [
                "Есть небольшое повышение СОЭ (при норме до 20 мм/ч).",
                "Остальные показатели крови без значимых отклонений.",
            ],
            "what_it_means": [
                "Сам по себе такой уровень СОЭ часто не указывает на заболевание.",
                "Может быть: реакцией на стресс или нагрузку, лёгким воспалением, индивидуальной особенностью.",
                "Важно: при нормальном ОАК это чаще не опасно.",
            ],
            "what_to_do": [
                "Если нет жалоб — ничего срочного делать не нужно.",
                "Оценить самочувствие: есть ли слабость, температура, боль.",
                "При сомнениях: сдать CRP, повторить ОАК через 2–4 недели.",
            ],
            "important": "Один показатель СОЭ без симптомов не используется для постановки диагноза.",
        }
        if "CRP" not in str(next_tests):
            next_tests.append("CRP (более точный маркер воспаления)")
        if not any("2" in t and "недел" in t for t in next_tests):
            next_tests.append("Повтор ОАК через 2–4 недели")
        upsell_cta = {
            "show": True,
            "title": "Вы получили общую картину",
            "description": "Сейчас важно понять: это разовая реакция организма или устойчивый паттерн. Могу собрать для вас персональный план: как отслеживать динамику, какие показатели реально важны, что делать, если СОЭ снова вырастет.",
            "cta_label": "Получить полный план",
            "cta_link": "#personal-cabinet",
        }

    return {
        "document_type": "cbc_with_reticulocytes" if ret_abs is not None or any("Reticulocyte" in v.marker for v in values) else "cbc",
        "confidence": 0.9,
        "summary": summary,
        "key_abnormalities": key_abnormalities,
        "pattern_interpretation": pattern_interpretation,
        "working_hypotheses": working_hypotheses,
        "next_tests": next_tests,
        "urgency_signals": urgency_signals,
        "limitations": limitations,
        "grouped_interpretation": grouped_interpretation,
        "patient_friendly": patient_friendly,
        "upsell_cta": upsell_cta,
    }


def build_cbc_report(
    doc: Dict[str, Any],
    extracted_text: str,
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Строит полный physician report для CBC/cbc_with_reticulocytes.
    Совместим с build_lab_report_from_doc (abnormal_findings, summary, recommended_followup_table и т.д.).
    """
    values = extract_cbc_values(extracted_text)
    interp = interpret_cbc(values)
    derived_indices = compute_derived_indices_for_document(extracted_text, values)

    filename = doc.get("filename") or "ОАК"

    # Единый реестр: key_abnormalities → abnormal_findings и borderline_markers_table из одних и тех же данных
    key_abns = interp.get("key_abnormalities", [])
    abnormal = []
    borderline_rows = []
    for a in key_abns:
        status = a.get("status") or ""
        mcode = str(a.get("marker") or "")
        mlabel = cbc_label_ru(mcode)
        row = {
            "marker": mlabel,
            "name": mlabel,
            "marker_code": mcode,
            "value": str(a.get("value", "")),
            "ref_low": str(a.get("ref_low", "")) if a.get("ref_low") is not None else "",
            "ref_high": str(a.get("ref_high", "")) if a.get("ref_high") is not None else "",
            "direction": "high" if status in ("high", "borderline_high", "critical") else "low" if status in ("low", "borderline_low") else "",
            "flag": status if status in ("borderline_high", "borderline_low") else ("high" if status in ("high", "significant_high", "critical") else "low" if status in ("low", "significant_low") else ""),
            "comment": a.get("clinical_note", ""),
        }
        abnormal.append(row)
        if status in ("borderline_high", "borderline_low"):
            borderline_rows.append({
                "name": row["name"],
                "category": "",
                "value": row["value"],
                "ref_low": row["ref_low"],
                "ref_high": row["ref_high"],
                "flag": status,
                "comment": row["comment"],
            })

    def _basis_for_hypothesis(h_text: str, data: Dict[str, Any]) -> str:
        """Не дублировать summary в «Основание», если он цитирует ту же гипотезу."""
        summ = str(data.get("summary") or "").strip()
        if summ and (h_text in summ or summ in h_text):
            notes = []
            for a in data.get("key_abnormalities", [])[:6]:
                m = str(a.get("marker") or "")
                cn = str(a.get("clinical_note") or "").strip()
                mru = cbc_label_ru(m)
                if m and cn:
                    notes.append(f"{mru}: {cn}")
                elif m:
                    notes.append(mru)
            return "; ".join(notes) if notes else ""
        return summ

    hypotheses = [
        {
            "hypothesis": h,
            "basis": _basis_for_hypothesis(h, interp),
            "comment": "Это рабочая гипотеза, а не диагноз.",
        }
        for h in interp.get("working_hypotheses", [])
    ]
    followup = [
        {"direction": "Лаборатория", "check": t, "why": "Уточнение клинической картины", "priority": "Средний"}
        for t in interp.get("next_tests", [])
    ]

    summary_lines = interp.get("pattern_interpretation", []) or []
    if interp.get("working_hypotheses"):
        summary_lines = list(interp["working_hypotheses"][:4]) + summary_lines

    _doc_t = str(interp.get("document_type") or "cbc")
    professional_summary = _build_cbc_professional_summary(
        interp, values, derived_indices, extracted_text=extracted_text, document_type=_doc_t
    )
    derived_section_physician = format_derived_indices_section(derived_indices, for_patient=False)
    derived_section_patient = format_derived_indices_section(derived_indices, for_patient=True)

    return {
        "doc_type": interp.get("document_type", "cbc"),
        "document_type": interp.get("document_type", "cbc"),
        "document_name": filename,
        "document_summary": {},
        "patient": {},
        "summary": summary_lines if summary_lines else [interp.get("summary", "ОАК: см. ключевые отклонения и гипотезы.")],
        "abnormal_findings": abnormal,
        "abnormal_markers_table": abnormal,
        "borderline_markers_table": borderline_rows,
        "recommended_followup_table": followup,
        "top_hypotheses_table": hypotheses,
        "grouped_interpretation_table": interp.get("grouped_interpretation", []),
        "interpretation": summary_lines,
        "follow_up": {
            "tests": interp.get("next_tests", []),
            "referrals": [],
            "notes": interp.get("urgency_signals", []),
        },
        "limitations": interp.get("limitations", []),
        "professional_summary": professional_summary,
        "derived_indices": [d.model_dump() for d in derived_indices],
        "derived_indices_section_physician": derived_section_physician,
        "derived_indices_section_patient": derived_section_patient,
        "patient_friendly": interp.get("patient_friendly") or {},
        "upsell_cta": interp.get("upsell_cta") or {},
        "analysis_label_ru": _cbc_analysis_title_ru(extracted_text, _doc_t),
    }


def _cbc_analysis_title_ru(extracted_text: str, document_type: str = "") -> str:
    """Подпись типа исследования как на бланке (РФ): общеклинический ОАК с лейкоформулой."""
    low = (extracted_text or "").lower()
    dt = (document_type or "").lower()
    clinical = "общеклинический" in low or "лейкоцитарн" in low or "лейкоформул" in low
    if clinical:
        if "cbc_with" in dt or "ретикулоцит" in low:
            return "Общеклинический анализ крови с лейкоцитарной формулой и ретикулоцитами"
        return "Общеклинический анализ крови с лейкоцитарной формулой"
    if "cbc_with" in dt:
        return "Общий анализ крови с ретикулоцитами (ОАК)"
    return "Общий анализ крови (ОАК)"


def _build_cbc_professional_summary(
    interp: Dict[str, Any],
    values: List[LabValue],
    derived_indices: Optional[List[DerivedIndex]] = None,
    *,
    extracted_text: str = "",
    document_type: str = "",
) -> str:
    parts = [_cbc_analysis_title_ru(extracted_text, document_type)]
    parts.append("")
    if interp.get("key_abnormalities"):
        parts.append("Ключевые отклонения:")
        for a in interp["key_abnormalities"][:10]:
            mshow = cbc_label_ru(str(a.get("marker") or ""))
            parts.append(f"- {mshow}: {a.get('value')} {a.get('unit', '')} ({a.get('status')}) — {a.get('clinical_note', '')}")
    else:
        parts.append("Показатели в пределах референса; существенных отклонений не выявлено.")
    parts.append("")
    if derived_indices:
        di_block = format_derived_indices_section(derived_indices, for_patient=False)
        if di_block:
            parts.append(di_block)
            parts.append("")
    if interp.get("working_hypotheses"):
        parts.append("Рабочие гипотезы:")
        for h in interp["working_hypotheses"][:5]:
            parts.append(f"- {h}")
    parts.append("")
    if interp.get("next_tests"):
        parts.append("Рекомендуемые проверки:")
        for t in interp["next_tests"][:8]:
            parts.append(f"- {t}")
    return "\n".join(parts)
