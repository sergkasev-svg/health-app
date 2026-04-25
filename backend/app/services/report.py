from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.document_physician_report import (
    build_document_physician_report,
    format_document_physician_report,
)
from app.services.pretty_physician_report_tables import (
    _friendly_doc_type_label,
    build_physician_report_html,
)
from app.services.clinical_routing_engine import build_clinical_routing_output
from app.services.unified_lab_report_presenter import build_unified_lab_report_presenter
from app.services.marker_table_filters import is_junk_marker_narrative as _is_junk_marker_narrative
from app.services.cbc_display_labels import cbc_abnormal_row_dedup_key

DISCLAIMER_TEXT = "Информация носит справочный характер и не заменяет консультацию врача."
METABOLIC_EDU_DISCLAIMER = "Информация носит образовательный характер и не заменяет консультацию врача."


# ---------------------------------------------------------
# text safety helpers
# ---------------------------------------------------------

def _strip_html_tags(text: str) -> str:
    s = str(text or "")
    s = re.sub(r"(?is)<script.*?>.*?</script>", " ", s)
    s = re.sub(r"(?is)<style.*?>.*?</style>", " ", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _clean_plain_text_block(text: str) -> str:
    s = _strip_html_tags(str(text or ""))
    s = s.replace(" .", ".").replace("..", ".")
    return s.strip()


def _clean_plain_text_preserve_lines(text: str) -> str:
    """Чистит HTML, но сохраняет переносы строк для читаемого многостраничного отчёта."""
    s = str(text or "")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"(?is)<script.*?>.*?</script>", " ", s)
    s = re.sub(r"(?is)<style.*?>.*?</style>", " ", s)
    s = re.sub(r"(?is)<br\s*/?>", "\n", s)
    s = re.sub(r"(?is)</p>", "\n", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    lines = []
    for ln in s.split("\n"):
        ln = re.sub(r"\s+", " ", ln).strip()
        if ln:
            lines.append(ln)
    return "\n".join(lines).strip()


def _safe_case_summary(text: str, fallback: str = "Клиническая сводка по загруженному документу.") -> str:
    s = _clean_plain_text_block(text)
    if not s:
        return fallback
    if len(s) > 700:
        s = s[:700].rstrip()
        if " " in s:
            s = s.rsplit(" ", 1)[0]
        s += "…"
    return s


def _safe_professional_summary(text: str) -> str:
    return _clean_plain_text_block(text)


def _strip_internal_codes(text: str) -> str:
    """Убирает служебные snake_case коды из пользовательских сводок."""
    s = str(text or "")
    s = re.sub(r"\b[a-z][a-z0-9]*(?:_[a-z][a-z0-9_]*)+\b", " ", s)
    s = re.sub(r"\s*,\s*,+", ",", s)
    s = re.sub(r"[,\s]+,", ",", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" ,")
    return s


def _safe_aggregate_short(text: str, max_len: int = 340) -> str:
    s = _strip_internal_codes(_clean_plain_text_block(text))
    if len(s) <= max_len:
        return s
    s = s[:max_len].rstrip()
    if " " in s:
        s = s.rsplit(" ", 1)[0]
    return s.rstrip(",;:- ") + "…"


def _safe_aggregate_excerpt(text: str, max_len: int = 5000) -> str:
    s = _strip_internal_codes(_clean_plain_text_preserve_lines(text))
    if len(s) <= max_len:
        return s
    s = s[:max_len].rstrip()
    if " " in s:
        s = s.rsplit(" ", 1)[0]
    return s.rstrip(",;:- ") + "…"


def _dedup(items: List[str], limit: int = 999) -> List[str]:
    out: List[str] = []
    seen = set()
    for x in items or []:
        s = str(x or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _extract_presenter_brain_lists(present: Dict[str, Any]) -> Dict[str, List[str]]:
    scenario = present.get("scenario_output") if isinstance(present, dict) else {}
    brain = scenario.get("brain_report") if isinstance(scenario, dict) else {}
    if not isinstance(brain, dict):
        brain = {}

    hypos: List[str] = []
    for row in (brain.get("hypotheses") or []):
        if isinstance(row, dict):
            lbl = str(row.get("label") or row.get("hypothesis") or "").strip()
            if lbl:
                hypos.append(lbl)
        else:
            val = str(row or "").strip()
            if val:
                hypos.append(val)

    tests = [str(x).strip() for x in (brain.get("what_to_add") or []) if str(x).strip()]
    tests.extend([str(x).strip() for x in ((brain.get("plan") or {}).get("tests") or []) if str(x).strip()])
    nutrition = [str(x).strip() for x in (brain.get("nutrition") or []) if str(x).strip()]
    activity = [str(x).strip() for x in (brain.get("activity") or []) if str(x).strip()]

    return {
        "hypotheses": _dedup(hypos, limit=8),
        "diagnostics": _dedup(tests, limit=12),
        "nutrition": _dedup(nutrition, limit=8),
        "activity": _dedup(activity, limit=8),
    }


# ---------------------------------------------------------
# organic acids special route
# ---------------------------------------------------------

def _build_organic_acids_only_report(
    doc: dict,
    doc_physician: dict,
    profile: Optional[dict],
    profile_lines: list[str],
    caution_lines: list[str],
    compact_for_doctor: bool,
) -> dict[str, Any]:
    """
    Финальный organic acids pipeline:
    physician formatter -> html -> routing -> unified presenter -> final API shape
    """
    filename = doc.get("filename") or "document"

    # 1. HTML для врача
    physician_html = doc_physician.get("physician_report_html")
    if not physician_html:
        physician_html = build_physician_report_html(doc_physician)

    doc_physician["physician_report_html"] = physician_html

    # 2. routing
    routing = build_clinical_routing_output(doc_physician)

    # 3. unified presenter
    present = build_unified_lab_report_presenter(
        filename=filename,
        document_type=str(doc_physician.get("doc_type") or "organic_acids_urine"),
        physician_report=doc_physician,
        routing_output=routing,
    )
    brain_lists = _extract_presenter_brain_lists(present)

    # 4. summary blocks
    summary_lines = [str(x).strip() for x in (doc_physician.get("summary") or []) if str(x).strip()]
    follow_table = doc_physician.get("recommended_followup_table") or []
    hypo_table = doc_physician.get("top_hypotheses_table") or []

    hypotheses: List[str] = []
    for h in hypo_table:
        if isinstance(h, dict):
            val = str(h.get("hypothesis") or "").strip()
            if val:
                hypotheses.append(val)
        else:
            val = str(h).strip()
            if val:
                hypotheses.append(val)

    diagnostics = [
        str(row.get("check") or "").strip()
        for row in follow_table[:8]
        if str(row.get("check") or "").strip()
    ]
    hypotheses = _dedup(hypotheses + brain_lists.get("hypotheses", []), limit=8)
    diagnostics = _dedup(diagnostics + brain_lists.get("diagnostics", []), limit=12)
    abnormal_markers_table = _normalize_marker_rows(
        doc_physician.get("abnormal_markers_table") or doc_physician.get("abnormal_findings") or [],
        limit=10,
    )

    professional_summary = format_document_physician_report(doc_physician)
    professional_summary = _safe_professional_summary(professional_summary)

    case_summary = _safe_case_summary(
        str(present.get("case_summary") or "").strip(),
        fallback=f"Профиль органических кислот по документу {filename} требует клинической оценки.",
    )

    display_summary = str(present.get("display_summary") or "").strip()
    user_summary = str(present.get("user_summary") or "").strip()
    safe_next_steps = str(present.get("safe_next_steps") or "").strip()
    when_urgent = str(present.get("when_urgent") or "").strip()
    user_report_text = str(present.get("user_report_text") or "").strip()
    user_report_structured = present.get("user_report_structured") or {}

    routed_doctor = routing.get("doctor") or {}
    routed_conclusions = [
        str(x).strip()
        for x in (routed_doctor.get("routing_conclusions") or [])
        if str(x).strip()
    ]
    conclusions = routed_conclusions[:5] or summary_lines[:5]

    return {
        "case_summary": case_summary,
        "severity_index": "GREEN",
        "safe_next_steps": safe_next_steps,
        "when_urgent": when_urgent,
        "confidence": "Medium",
        "disclaimer": DISCLAIMER_TEXT,
        "educational_disclaimer": METABOLIC_EDU_DISCLAIMER,
        "user_summary": user_summary,
        "display_summary": display_summary,
        "professional_summary": professional_summary,
        "pattern_main_conclusion": str(doc_physician.get("pattern_main_conclusion") or "").strip(),
        "pattern_summary_headline": str(doc_physician.get("pattern_summary_headline") or "").strip(),
        "clinical_patterns": doc_physician.get("clinical_patterns") or [],
        "physician_report_html": physician_html,
        "conclusions": conclusions,
        "diagnosis_hints": [],
        "treatment": [],
        "nutrition": brain_lists.get("nutrition") or [],
        "activity": brain_lists.get("activity") or [],
        "prevention": [],
        "extracted_text": (doc.get("extracted_text") or "").strip(),
        "document_name": filename,
        "document_type": str(doc_physician.get("doc_type") or "organic_acids_urine"),
        "modern_evidence": [],
        "evidence_links": [],
        "profile_context": profile_lines,
        "profile_cautions": caution_lines,
        "medication_warnings": [],
        "input_data": ["Документ: " + filename, "Органические кислоты в моче"],
        "findings": summary_lines[:8],
        "hypotheses": hypotheses[:5],
        "diagnosis": [],
        "treatment_plan": [],
        "medications": [],
        "alternative_treatment": [],
        "physical_exercises": [],
        "diagnostics": diagnostics,
        "abnormal_markers_table": abnormal_markers_table,
        "evidence_notes": [],
        "evidence_sources": [],
        "medical_reasoning": {},
        "metabolic_sections": {},
        "metabolic_overview": summary_lines[:8],
        "metabolite_tables": {},
        "thematic_metabolite_sections": {},
        "grouped_hypotheses": {},
        "unified_recommendations": {},
        "glossary_terms": [],
        "compact_for_doctor": bool(compact_for_doctor),
        "user_report_structured": user_report_structured,
        "user_report_text": user_report_text,
        "user_hypotheses": [],
        "scenario_output": present.get("scenario_output") or {},
        "debug_user_report": {
            "routing": routing,
            "presenter": present.get("presenter_debug") or {},
        },
    }


# ---------------------------------------------------------
# generic fallback doc route
# ---------------------------------------------------------

def _build_generic_document_report(
    doc: dict,
    doc_physician: dict,
    profile_lines: list[str],
    caution_lines: list[str],
    compact_for_doctor: bool,
) -> dict[str, Any]:
    filename = doc.get("filename") or "document"

    physician_html = doc_physician.get("physician_report_html")
    if not physician_html:
        physician_html = build_physician_report_html(doc_physician)
    doc_physician["physician_report_html"] = physician_html

    present = build_unified_lab_report_presenter(
        filename=filename,
        document_type=str(doc_physician.get("doc_type") or "generic_lab_document"),
        physician_report=doc_physician,
        routing_output={},
    )
    brain_lists = _extract_presenter_brain_lists(present)

    summary_lines = [str(x).strip() for x in (doc_physician.get("summary") or []) if str(x).strip()]
    follow_table = doc_physician.get("recommended_followup_table") or []
    hypo_table = doc_physician.get("top_hypotheses_table") or []

    hypotheses: List[str] = []
    for h in hypo_table:
        if isinstance(h, dict):
            val = str(h.get("hypothesis") or "").strip()
            if val:
                hypotheses.append(val)
        else:
            val = str(h).strip()
            if val:
                hypotheses.append(val)

    diagnostics = [
        str(row.get("check") or "").strip()
        for row in follow_table[:8]
        if str(row.get("check") or "").strip()
    ]
    hypotheses = _dedup(hypotheses + brain_lists.get("hypotheses", []), limit=8)
    diagnostics = _dedup(diagnostics + brain_lists.get("diagnostics", []), limit=12)
    abnormal_markers_table = _normalize_marker_rows(
        doc_physician.get("abnormal_markers_table") or doc_physician.get("abnormal_findings") or [],
        limit=10,
    )

    return {
        "case_summary": _safe_case_summary(str(present.get("case_summary") or "").strip()),
        "severity_index": "GREEN",
        "safe_next_steps": str(present.get("safe_next_steps") or "").strip(),
        "when_urgent": str(present.get("when_urgent") or "").strip(),
        "confidence": "Medium",
        "disclaimer": DISCLAIMER_TEXT,
        "educational_disclaimer": METABOLIC_EDU_DISCLAIMER,
        "user_summary": str(present.get("user_summary") or "").strip(),
        "display_summary": str(present.get("display_summary") or "").strip(),
        "professional_summary": _safe_professional_summary(format_document_physician_report(doc_physician)),
        "pattern_main_conclusion": str(doc_physician.get("pattern_main_conclusion") or "").strip(),
        "pattern_summary_headline": str(doc_physician.get("pattern_summary_headline") or "").strip(),
        "clinical_patterns": doc_physician.get("clinical_patterns") or [],
        "physician_report_html": physician_html,
        "conclusions": summary_lines[:5],
        "diagnosis_hints": [],
        "treatment": [],
        "nutrition": brain_lists.get("nutrition") or [],
        "activity": brain_lists.get("activity") or [],
        "prevention": [],
        "extracted_text": (doc.get("extracted_text") or "").strip(),
        "document_name": filename,
        "document_type": str(doc_physician.get("doc_type") or "generic_lab_document"),
        "modern_evidence": [],
        "evidence_links": [],
        "profile_context": profile_lines,
        "profile_cautions": caution_lines,
        "medication_warnings": [],
        "input_data": ["Документ: " + filename],
        "findings": summary_lines[:8],
        "hypotheses": hypotheses[:5],
        "diagnosis": [],
        "treatment_plan": [],
        "medications": [],
        "alternative_treatment": [],
        "physical_exercises": [],
        "diagnostics": diagnostics,
        "abnormal_markers_table": abnormal_markers_table,
        "evidence_notes": [],
        "evidence_sources": [],
        "medical_reasoning": {},
        "metabolic_sections": {},
        "metabolic_overview": summary_lines[:8],
        "metabolite_tables": {},
        "thematic_metabolite_sections": {},
        "grouped_hypotheses": {},
        "unified_recommendations": {},
        "glossary_terms": [],
        "compact_for_doctor": bool(compact_for_doctor),
        "user_report_structured": present.get("user_report_structured") or {},
        "user_report_text": str(present.get("user_report_text") or "").strip(),
        "user_hypotheses": [],
        "scenario_output": present.get("scenario_output") or {},
        "debug_user_report": {
            "presenter": present.get("presenter_debug") or {},
        },
    }


def _build_fallback_report(
    doc: dict,
    profile_lines: list[str],
    caution_lines: list[str],
    compact_for_doctor: bool,
) -> dict[str, Any]:
    filename = doc.get("filename") or "document"
    display_summary = "Недостаточно данных для интерпретации"
    user_summary = "Не удалось корректно распознать данные анализа."
    has_no_text = not (doc.get("extracted_text") or "").strip()
    safe_next_steps = (
        "Попробуйте загрузить документ повторно (фото страницы или PDF с текстовым слоем). "
        "Если файл — скан, убедитесь, что изображение чёткое. Или покажите оригинал анализа врачу."
        if has_no_text
        else "Попробуйте загрузить документ повторно или показать оригинал анализа врачу."
    )
    when_urgent = ""

    return {
        "case_summary": f"Анализ {filename} требует клинической интерпретации.",
        "severity_index": "UNKNOWN",
        "safe_next_steps": safe_next_steps,
        "when_urgent": when_urgent,
        "confidence": "Low",
        "disclaimer": DISCLAIMER_TEXT,
        "educational_disclaimer": METABOLIC_EDU_DISCLAIMER,
        "user_summary": user_summary,
        "display_summary": display_summary,
        "professional_summary": "",
        "physician_report_html": "",
        "conclusions": [],
        "diagnosis_hints": [],
        "treatment": [],
        "nutrition": [],
        "activity": [],
        "prevention": [],
        "extracted_text": (doc.get("extracted_text") or "").strip(),
        "document_name": filename,
        "document_type": str(doc.get("type") or "unknown"),
        "modern_evidence": [],
        "evidence_links": [],
        "profile_context": profile_lines,
        "profile_cautions": caution_lines,
        "medication_warnings": [],
        "input_data": ["Документ: " + filename],
        "findings": [],
        "hypotheses": [],
        "diagnosis": [],
        "treatment_plan": [],
        "medications": [],
        "alternative_treatment": [],
        "physical_exercises": [],
        "diagnostics": [],
        "evidence_notes": [],
        "evidence_sources": [],
        "medical_reasoning": {},
        "metabolic_sections": {},
        "metabolic_overview": [],
        "metabolite_tables": {},
        "thematic_metabolite_sections": {},
        "grouped_hypotheses": {},
        "unified_recommendations": {},
        "glossary_terms": [],
        "compact_for_doctor": bool(compact_for_doctor),
        "user_report_structured": {
            "severity": "unknown",
            "headline": display_summary,
            "blocks": [
                {"title": "Что произошло", "items": [user_summary]},
                {"title": "Что делать дальше", "items": [safe_next_steps]},
            ],
        },
        "user_report_text": user_summary,
        "user_hypotheses": [],
        "debug_user_report": {},
    }


# ---------------------------------------------------------
# public API
# ---------------------------------------------------------

def _profile_clinical_context(
    profile: Optional[dict],
    lab_patient: Optional[dict] = None,
) -> dict[str, Any]:
    """
    Строки контекста для отчёта. Пол (и при необходимости др.) с бланка имеют приоритет над ЛК —
    чтобы анализ ребёнка не подменялся полом учётной записи взрослого.
    """
    p = profile or {}
    lp = lab_patient if isinstance(lab_patient, dict) else {}
    chronic = [str(x).strip() for x in (p.get("chronic_conditions") or []) if str(x).strip()]
    allergies = [str(x).strip() for x in (p.get("allergies") or []) if str(x).strip()]
    family = str(p.get("family_history") or "").strip()
    dob = str(p.get("date_of_birth") or "").strip()
    sex_raw = str(lp.get("sex") or "").strip() or str(p.get("sex") or "").strip()
    sex = ""
    if sex_raw:
        from app.services.lab_patient_demographics import _normalize_sex

        sex = _normalize_sex(sex_raw) or sex_raw

    profile_lines = []
    if dob:
        profile_lines.append("Дата рождения: " + dob)
    if sex:
        profile_lines.append("Пол: " + sex)
    if chronic:
        profile_lines.append("Хронические заболевания: " + ", ".join(chronic))
    if allergies:
        profile_lines.append("Аллергии: " + ", ".join(allergies))
    if family:
        profile_lines.append("Семейный анамнез: " + family)

    caution_lines = []
    if allergies:
        caution_lines.append("Проверить назначения на риск аллергических реакций: " + ", ".join(allergies))
    if chronic:
        caution_lines.append("Сверять лечение с хроническими состояниями: " + ", ".join(chronic))
    if family:
        caution_lines.append("Учесть семейный анамнез при дифференциальной диагностике.")

    return {
        "profile_lines": profile_lines,
        "caution_lines": caution_lines,
    }


def build_lab_report_from_doc(
    doc: dict,
    profile: Optional[dict] = None,
    *,
    task_query: str = "",
    dialog_context: str = "",
    compact_for_doctor: bool = False,
) -> dict[str, Any]:
    """
    Финальная единая точка сборки отчёта по одному документу.
    Совместима с router/API, который ожидает обычный dict.
    """
    _ = task_query
    _ = dialog_context

    doc_physician = build_document_physician_report(
        doc=doc,
        profile=profile,
        raw_hypotheses=None,
    )

    if not doc_physician:
        fb_ctx = _profile_clinical_context(profile)
        return _build_fallback_report(
            doc=doc,
            profile_lines=fb_ctx["profile_lines"],
            caution_lines=fb_ctx["caution_lines"],
            compact_for_doctor=compact_for_doctor,
        )

    lab_pat = doc_physician.get("patient") if isinstance(doc_physician.get("patient"), dict) else {}
    ctx = _profile_clinical_context(profile, lab_patient=lab_pat)
    profile_lines = ctx["profile_lines"]
    caution_lines = ctx["caution_lines"]

    doc_type = str(doc_physician.get("doc_type") or doc.get("type") or "").lower()

    if "organic_acids" in doc_type:
        return _build_organic_acids_only_report(
            doc=doc,
            doc_physician=doc_physician,
            profile=profile,
            profile_lines=profile_lines,
            caution_lines=caution_lines,
            compact_for_doctor=compact_for_doctor,
        )

    return _build_generic_document_report(
        doc=doc,
        doc_physician=doc_physician,
        profile_lines=profile_lines,
        caution_lines=caution_lines,
        compact_for_doctor=compact_for_doctor,
    )


def _aggregate_priority_level(text: str, document_type: str = "") -> str:
    s = str(text or "").lower()
    dt = str(document_type or "").lower()
    high_keys = ["лпнп", "ldl", "общий холестерин", "apo", "липопротеин(a)", "атероген", "высокий риск"]
    medium_keys = ["фруктозамин", "глюкоз", "инсулин", "триглицер", "сое", "esr", "реакция на кровь", "mpv", "p-lcr"]
    low_keys = ["без признаков", "не выявлено", "отрицатель", "в пределах", "норма"]
    if any(k in s for k in high_keys):
        return "high"
    if any(k in s for k in medium_keys):
        return "medium"
    if "lipid" in dt:
        return "high"
    if "cbc" in dt or "urine" in dt:
        return "low"
    if any(k in s for k in low_keys):
        return "low"
    return "medium"


def _aggregate_priority_label(level: str) -> str:
    if level == "high":
        return "Высокий"
    if level == "medium":
        return "Средний"
    return "Низкий"


def _biomaterial_label_by_type(document_type: str) -> str:
    d = str(document_type or "").lower()
    if "urine" in d:
        return "Моча"
    if "stool" in d:
        return "Кал"
    if "saliva" in d:
        return "Слюна"
    if "swab" in d or "skin" in d:
        return "Мазок / слизистая"
    return "Кровь"


def _extract_float_from_text(text: str, aliases: List[str]) -> Optional[float]:
    s = str(text or "")
    for a in aliases:
        pattern = rf"(?i)(?:{re.escape(a)})\s*[:=]?\s*([0-9]+(?:[.,][0-9]+)?)"
        m = re.search(pattern, s)
        if m:
            try:
                return float(str(m.group(1)).replace(",", "."))
            except Exception:
                continue
    return None


def _compute_aggregate_indices(profile: Optional[dict], single_reports: List[dict]) -> List[Dict[str, str]]:
    p = profile or {}
    out: List[Dict[str, str]] = []

    def _add(name: str, value: str, interp: str) -> None:
        if not value:
            return
        out.append({"name": name, "value": value, "interpretation": interp})

    # Anthropometrics / vitals
    h = p.get("height_cm") or p.get("height") or p.get("рост")
    w = p.get("weight_kg") or p.get("weight") or p.get("вес")
    sbp = p.get("systolic_bp") or p.get("bp_systolic") or p.get("sbp")
    dbp = p.get("diastolic_bp") or p.get("bp_diastolic") or p.get("dbp")
    hr = p.get("heart_rate") or p.get("pulse") or p.get("hr")
    try:
        hf = float(str(h).replace(",", ".")) if h is not None else None
        wf = float(str(w).replace(",", ".")) if w is not None else None
        if hf and wf and hf > 0:
            bmi = wf / ((hf / 100.0) ** 2)
            if bmi < 18.5:
                bmi_i = "ниже референсного диапазона"
            elif bmi < 25:
                bmi_i = "в пределах условной нормы"
            elif bmi < 30:
                bmi_i = "повышен"
            else:
                bmi_i = "существенно повышен"
            _add("BMI", f"{bmi:.1f}", bmi_i)
    except Exception:
        pass
    try:
        sbpf = float(str(sbp).replace(",", ".")) if sbp is not None else None
        dbpf = float(str(dbp).replace(",", ".")) if dbp is not None else None
        hrf = float(str(hr).replace(",", ".")) if hr is not None else None
        if sbpf and dbpf and hrf and hrf > 0:
            mean_bp = dbpf + (sbpf - dbpf) / 3.0
            kerdo = (1.0 - (mean_bp / hrf)) * 100.0
            _add("Индекс Кердо", f"{kerdo:.1f}", "поддерживающий индекс вегетативного баланса")
    except Exception:
        pass

    # CBC-derived
    cbc_text = "\n".join(
        [
            str(r.get("professional_summary") or "")
            for r in single_reports
            if "cbc" in str(r.get("document_type") or "").lower() or "blood_count" in str(r.get("document_type") or "").lower()
        ]
    )
    if not cbc_text:
        cbc_text = "\n".join([str(r.get("professional_summary") or "") for r in single_reports])
    neut = _extract_float_from_text(cbc_text, ["neutrophils", "нейтрофилы", "neu"])
    lymph = _extract_float_from_text(cbc_text, ["lymphocytes", "лимфоциты", "lym"])
    mono = _extract_float_from_text(cbc_text, ["monocytes", "моноциты", "mon"])
    plate = _extract_float_from_text(cbc_text, ["platelets", "тромбоциты", "plt"])
    if neut and lymph and lymph > 0:
        nlr = neut / lymph
        _add("NLR", f"{nlr:.2f}", "расчётный индекс воспалительного баланса")
        if plate and plate > 0:
            sii = (plate * neut) / lymph
            _add("SII", f"{sii:.1f}", "поддерживающий индекс системного воспаления")
    if neut and mono and lymph and lymph > 0:
        siri = (neut * mono) / lymph
        _add("SIRI", f"{siri:.2f}", "поддерживающий индекс иммунно-воспалительного профиля")

    return out[:8]


def _group_checks_by_priority(checks: List[str]) -> Dict[str, List[str]]:
    high_keys = ["apob", "липопротеин(a)", "lp(a)", "липид", "ldl", "холестерин"]
    medium_keys = ["ттг", "глюкоз", "hba1c", "фруктозамин"]
    optional_keys = ["homa", "инсулин", "повтор оам", "повтор оак", "по клинической необходимости"]
    grouped = {"high": [], "medium": [], "optional": []}
    for c in checks or []:
        s = str(c or "").strip()
        if not s:
            continue
        low = s.lower()
        if any(k in low for k in high_keys):
            grouped["high"].append(s)
        elif any(k in low for k in medium_keys):
            grouped["medium"].append(s)
        elif any(k in low for k in optional_keys):
            grouped["optional"].append(s)
        else:
            grouped["medium"].append(s)
    grouped["high"] = _dedup(grouped["high"], limit=8)
    grouped["medium"] = _dedup(grouped["medium"], limit=8)
    grouped["optional"] = _dedup(grouped["optional"], limit=8)
    return grouped


def _derive_working_hypotheses(main_priority: str, all_hypotheses: List[str], all_findings: List[str]) -> List[str]:
    out = _dedup([str(x).strip() for x in (all_hypotheses or []) if str(x).strip()], limit=6)
    blob = (" ".join(all_findings or []) + " " + (main_priority or "")).lower()
    if any(k in blob for k in ["ldl", "лпнп", "холестерин", "атероген"]):
        out.insert(0, "Атерогенная дислипидемия")
        out.append("Возможна первичная (семейная) гиперхолестеринемия")
    if any(k in blob for k in ["фруктозамин", "глюкоз", "hba1c"]):
        out.append("Возможны ранние нарушения углеводного обмена")
    return _dedup(out, limit=6)


def _normalize_marker_rows(rows: Any, *, limit: int = 8) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        marker = str(row.get("marker") or row.get("name") or row.get("label") or "").strip()
        value = str(row.get("value") or row.get("result") or "").strip()
        ref_low = str(row.get("ref_low") or "").strip()
        ref_high = str(row.get("ref_high") or "").strip()
        ref = str(row.get("reference") or "").strip()
        if not ref:
            if ref_low and ref_high:
                ref = f"{ref_low}–{ref_high}"
            elif ref_low:
                ref = f">= {ref_low}"
            elif ref_high:
                ref = f"<= {ref_high}"
        comment = str(row.get("comment") or row.get("summary") or "").strip()
        if _is_junk_marker_narrative(marker, comment):
            continue
        if not marker and not value and not comment:
            continue
        out.append(
            {
                "marker": marker or "Показатель",
                "value": value or "—",
                "reference": ref or "—",
                "comment": comment or "—",
            }
        )
        if len(out) >= limit:
            break
    return out


def _merge_patient_meta_from_reports(single_reports: List[dict]) -> Dict[str, Any]:
    """Берёт первые непустые поля пациента из отчётов по документам."""
    keys = ("display_name", "sex", "age_years", "birth_year", "sample_type", "collection_date", "report_date")
    out: Dict[str, Any] = {}
    for r in single_reports:
        p = r.get("patient") if isinstance(r.get("patient"), dict) else {}
        for k in keys:
            if k in out and out[k] not in (None, "", "—"):
                continue
            v = p.get(k)
            if v is not None and str(v).strip() and str(v).strip() != "—":
                out[k] = v
    return out


def build_aggregate_physician_report_html(
    aggregate_result: Dict[str, Any],
    single_reports: List[dict],
) -> str:
    """
    Полноразмерный HTML «Отчёт для врача» для сводного случая: шапка, отклонения по всем файлам,
    паттерны, гипотезы, дообследование, ограничения (для PDF/скачивания).
    """
    pm = str(aggregate_result.get("pattern_main_conclusion") or "").strip()
    prof = str(aggregate_result.get("professional_summary") or "").strip()
    agg = aggregate_result.get("aggregate_clinical") if isinstance(aggregate_result.get("aggregate_clinical"), dict) else {}

    abnormal: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for r in single_reports:
        for row in (r.get("abnormal_markers_table") or r.get("abnormal_findings") or []):
            if not isinstance(row, dict):
                continue
            mk = str(row.get("marker") or row.get("name") or "").strip()
            if _is_junk_marker_narrative(mk, str(row.get("comment") or "")):
                continue
            dedup = cbc_abnormal_row_dedup_key(row) or mk.lower()
            key = (dedup + "|" + str(row.get("value") or "")).lower()[:120]
            if key in seen:
                continue
            seen.add(key)
            abnormal.append(row)
    if not abnormal:
        for ds in aggregate_result.get("aggregate_document_sections") or []:
            if not isinstance(ds, dict):
                continue
            for mr in ds.get("key_marker_rows") or []:
                if not isinstance(mr, dict):
                    continue
                m = str(mr.get("marker") or "").strip()
                if _is_junk_marker_narrative(m, str(mr.get("comment") or "")):
                    continue
                if not m and not str(mr.get("value") or "").strip():
                    continue
                abnormal.append(
                    {
                        "marker": m or "Показатель",
                        "value": str(mr.get("value") or "—"),
                        "ref_low": "",
                        "ref_high": "",
                        "direction": "",
                        "comment": str(mr.get("comment") or "—"),
                    }
                )

    hypos: List[Dict[str, str]] = []
    for r in single_reports:
        for h in r.get("top_hypotheses_table") or []:
            if isinstance(h, dict) and (h.get("hypothesis") or h.get("basis")):
                hypos.append(h)
            elif str(h or "").strip():
                hypos.append({"hypothesis": str(h).strip(), "basis": "", "comment": ""})

    follow_rows: List[Dict[str, str]] = []
    for x in aggregate_result.get("diagnostics") or []:
        sx = str(x or "").strip()
        if sx:
            follow_rows.append(
                {
                    "direction": "Рекомендации",
                    "check": sx,
                    "why": "По совокупности загруженных данных",
                    "priority": "Средний",
                }
            )
    for bucket, label in (("high", "Высокий"), ("medium", "Средний"), ("optional", "По показаниям")):
        for x in (agg.get("next_checks_grouped") or {}).get(bucket) or []:
            sx = str(x or "").strip()
            if sx:
                follow_rows.append(
                    {
                        "direction": label,
                        "check": sx,
                        "why": "Сводный план",
                        "priority": label,
                    }
                )

    grouped: List[Dict[str, Any]] = []
    for ds in aggregate_result.get("aggregate_document_sections") or []:
        if not isinstance(ds, dict):
            continue
        grouped.append(
            {
                "group": str(ds.get("analysis_type_label_ru") or ds.get("filename") or "Документ"),
                "interpretation": str(ds.get("short_summary") or "")[:900],
            }
        )

    limitations = [str(x) for x in (agg.get("limitations") or []) if str(x).strip()]
    if not limitations:
        limitations = [
            "Интерпретация по совокупности загруженных данных не заменяет очную консультацию.",
        ]

    summary_lines: List[str] = []
    if pm:
        summary_lines.append(pm)
    elif prof:
        summary_lines.append(prof[:1200] + ("…" if len(prof) > 1200 else ""))

    payload: Dict[str, Any] = {
        "doc_type": "aggregate_clinical_report",
        "document_type": "aggregate_clinical_report",
        "document_name": aggregate_result.get("document_name") or "Сводный отчёт",
        "report_title": "Отчёт для врача",
        "report_subtitle": "Сводный клинический отчёт по загруженным документам",
        "patient": _merge_patient_meta_from_reports(single_reports),
        "document_summary": {},
        "pattern_main_conclusion": pm,
        "summary": summary_lines or [aggregate_result.get("display_summary") or "Сводный анализ загруженных исследований."],
        "abnormal_markers_table": abnormal[:32],
        "abnormal_findings": abnormal[:32],
        "top_hypotheses_table": hypos[:16],
        "recommended_followup_table": follow_rows[:20],
        "grouped_interpretation_table": grouped,
        "limitations": limitations,
        "clinical_patterns": aggregate_result.get("clinical_patterns_merged") or [],
    }
    try:
        return build_physician_report_html(payload)
    except Exception:
        return ""


def build_lab_report_from_docs(
    docs: List[dict],
    *,
    case_name: str = "Сводный отчёт",
    profile: Optional[dict] = None,
    task_query: str = "",
    dialog_context: str = "",
    compact_for_doctor: bool = False,
) -> dict[str, Any]:
    """
    Совместимый сводный отчёт по нескольким документам.
    Сейчас делает безопасную агрегацию без ложной глубокой интерпретации.
    """
    _ = task_query
    _ = dialog_context

    if not docs:
        return {
            "case_summary": "Нет документов для анализа.",
            "severity_index": "UNKNOWN",
            "safe_next_steps": "Загрузите документы повторно.",
            "when_urgent": "",
            "confidence": "Low",
            "disclaimer": DISCLAIMER_TEXT,
            "educational_disclaimer": METABOLIC_EDU_DISCLAIMER,
            "user_summary": "Нет документов для анализа.",
            "display_summary": "Нет документов",
            "professional_summary": "",
            "physician_report_html": "",
            "conclusions": [],
            "diagnosis_hints": [],
            "treatment": [],
            "nutrition": [],
            "activity": [],
            "prevention": [],
            "extracted_text": "",
            "document_name": case_name,
            "document_type": "aggregate_clinical_report",
            "modern_evidence": [],
            "evidence_links": [],
            "profile_context": [],
            "profile_cautions": [],
            "medication_warnings": [],
            "input_data": [],
            "findings": [],
            "hypotheses": [],
            "diagnosis": [],
            "treatment_plan": [],
            "medications": [],
            "alternative_treatment": [],
            "physical_exercises": [],
            "diagnostics": [],
            "evidence_notes": [],
            "evidence_sources": [],
            "medical_reasoning": {},
            "metabolic_sections": {},
            "metabolic_overview": [],
            "metabolite_tables": {},
            "thematic_metabolite_sections": {},
            "grouped_hypotheses": {},
            "unified_recommendations": {},
            "glossary_terms": [],
            "compact_for_doctor": bool(compact_for_doctor),
            "user_report_structured": {},
            "user_report_text": "",
            "user_hypotheses": [],
            "debug_user_report": {},
        }

    single_reports = [
        build_lab_report_from_doc(
            d,
            profile=profile,
            task_query="",
            dialog_context="",
            compact_for_doctor=compact_for_doctor,
        )
        for d in docs
    ]

    aggregate_document_sections: list[dict[str, Any]] = []
    matrix_rows: list[dict[str, str]] = []
    findings_all = _dedup([x for r in single_reports for x in (r.get("findings") or [])], limit=20)
    hypotheses = _dedup([x for r in single_reports for x in (r.get("hypotheses") or [])], limit=12)
    diagnostics = _dedup([x for r in single_reports for x in (r.get("diagnostics") or [])], limit=14)
    not_supported = _dedup(
        [
            str(x).strip()
            for r in single_reports
            for x in (r.get("findings") or [])
            if isinstance(x, str) and ("не выяв" in x.lower() or "без признаков" in x.lower() or "отрицат" in x.lower())
        ],
        limit=8,
    )

    for i, (d, r) in enumerate(zip(docs, single_reports), start=1):
        dt = str(r.get("document_type") or r.get("doc_type") or "").strip()
        type_ru = _friendly_doc_type_label(dt, r)
        summary_src = str(r.get("display_summary") or r.get("user_summary") or r.get("case_summary") or "").strip()
        short = _safe_aggregate_short(summary_src)
        priority_level = _aggregate_priority_level(" ".join([short, str(r.get("professional_summary") or "")]), dt)
        priority_ru = _aggregate_priority_label(priority_level)
        marker_rows = _normalize_marker_rows(r.get("abnormal_markers_table") or [], limit=10)
        aggregate_document_sections.append(
            {
                "filename": str(d.get("filename") or f"Документ {i}"),
                "document_type": dt,
                "analysis_type_label_ru": type_ru,
                "short_summary": short or "Краткий вывод по документу недоступен.",
                "professional_excerpt": "",  # no raw child-report leakage in aggregate summary
                "key_marker_rows": marker_rows,
                "priority": priority_ru,
            }
        )
        matrix_rows.append(
            {
                "document": f"{i}. {type_ru or 'Лабораторный документ'}",
                "biomaterial": _biomaterial_label_by_type(dt),
                "main_conclusion": short or "Требует клинической оценки.",
                "priority": priority_ru,
            }
        )

    # Main/secondary integration
    high_rows = [x for x in matrix_rows if x["priority"] == "Высокий"]
    mid_rows = [x for x in matrix_rows if x["priority"] == "Средний"]
    low_rows = [x for x in matrix_rows if x["priority"] == "Низкий"]
    main_priority = (
        high_rows[0]["main_conclusion"]
        if high_rows
        else (mid_rows[0]["main_conclusion"] if mid_rows else (low_rows[0]["main_conclusion"] if low_rows else "Клинический приоритет требует уточнения."))
    )
    secondary = _dedup([x["main_conclusion"] for x in (mid_rows + low_rows)], limit=3)
    if not not_supported:
        not_supported = [
            "По доступным данным не подтверждается выраженный системный воспалительный сдвиг.",
            "Интерпретация требует клинического контекста и динамики.",
        ]
    merged_pattern_texts = [
        str(r.get("pattern_main_conclusion") or "").strip()
        for r in single_reports
        if str(r.get("pattern_main_conclusion") or "").strip()
    ]
    merged_pm = (
        "\n\n---\n\n".join(merged_pattern_texts)
        if len(merged_pattern_texts) > 1
        else (merged_pattern_texts[0] if merged_pattern_texts else "")
    )
    merged_ph = next(
        (
            str(r.get("pattern_summary_headline") or "").strip()
            for r in single_reports
            if str(r.get("pattern_summary_headline") or "").strip()
        ),
        "",
    )
    merged_clinical_patterns: list[dict[str, Any]] = []
    for r in single_reports:
        for p in r.get("clinical_patterns") or []:
            if isinstance(p, dict):
                merged_clinical_patterns.append(p)

    attention_zones = _dedup(
        [x["main_conclusion"] for x in (high_rows + mid_rows)] + findings_all[:10],
        limit=10,
    )
    # При интегрированном P1/P2-тексте зоны внимания = короткие метки паттернов (без повтора длинного вывода)
    if merged_pm and merged_clinical_patterns:
        pat_labels = _dedup(
            [str(p.get("label") or "").strip() for p in merged_clinical_patterns if str(p.get("label") or "").strip()],
            limit=10,
        )
        if pat_labels:
            attention_zones = pat_labels
    derived_indices = _compute_aggregate_indices(profile, single_reports)
    checks_grouped = _group_checks_by_priority(diagnostics)
    working_hypotheses = _derive_working_hypotheses(main_priority, hypotheses, findings_all)

    display_summary = "Сводный клинический отчёт по нескольким лабораторным исследованиям"
    case_summary = (
        "Основной клинический приоритет: "
        + main_priority
        + (" Вторичные находки: " + "; ".join(secondary[:2]) + "." if secondary else "")
    ).strip()
    if merged_pm:
        one_line = " ".join(merged_pm.split())[:520]
        if len(merged_pm) > 520:
            one_line = one_line.rstrip() + "…"
        case_summary = (merged_ph + " — " + one_line).strip() if merged_ph else one_line
    user_summary = case_summary
    safe_next_steps = (
        "1) Сначала обсудить главный приоритет с лечащим врачом. "
        "2) Выполнить дообследование по приоритету (без дублей и лишних тестов). "
        "3) Контроль вторичных находок — по симптомам и в динамике."
    )
    when_urgent = (
        "Срочно за медицинской помощью при боли в груди, выраженной одышке, потере сознания, "
        "сильном кровотечении, резком ухудшении самочувствия."
    )

    aggregate_clinical = {
        "title": "Сводный клинический отчёт по нескольким лабораторным исследованиям",
        "main_conclusion": {
            "main_priority": main_priority,
            "secondary_findings": secondary,
            "not_supported_by_data": not_supported[:3],
        },
        "document_matrix": matrix_rows,
        "attention_zones": attention_zones,
        "not_supported": not_supported,
        "derived_indices": derived_indices,
        "next_checks": diagnostics,
        "next_checks_grouped": checks_grouped,
        "working_hypotheses": working_hypotheses,
        "strategy": [
            "Основной фокус: клиническая оценка липидного/метаболического риска.",
            "Вторичные изменения: наблюдение и контроль в динамике по показаниям.",
            "Избегать избыточной диагностики вне ключевого приоритета.",
        ],
        "limitations": [
            "Интерпретация выполняется по лабораторным данным и не заменяет очную консультацию.",
            "Без жалоб, анамнеза и динамики любые гипотезы остаются вероятностными.",
        ],
        "urgent": when_urgent,
    }

    blocks: list[dict[str, Any]] = [
        {
            "kind": "main",
            "title": "Главный вывод",
            "items": [
                "Основной приоритет: " + main_priority,
                *["Вторично: " + x for x in secondary[:2]],
                "Не подтверждается: " + "; ".join(not_supported[:2]),
            ],
        },
        {
            "kind": "matrix",
            "title": "Сводка по документам",
            "items": [f"{row['document']} | {row['main_conclusion']} | Приоритет: {row['priority']}" for row in matrix_rows],
        },
        {
            "kind": "attention",
            "title": "Зоны внимания",
            "items": attention_zones[:6],
        },
        {
            "kind": "not_supported",
            "title": "Что по этим данным не подтверждается",
            "items": not_supported[:6],
        },
        {
            "kind": "checks",
            "title": "Что проверить дальше",
            "items": (
                [f"Высокий приоритет: {x}" for x in checks_grouped["high"]]
                + [f"Средний приоритет: {x}" for x in checks_grouped["medium"]]
                + [f"По показаниям: {x}" for x in checks_grouped["optional"]]
            )
            or ["Дообследование уточнить с лечащим врачом по клиническому приоритету."],
        },
    ]
    if working_hypotheses:
        blocks.append(
            {
                "kind": "hypotheses",
                "title": "Рабочие гипотезы (не диагнозы)",
                "items": working_hypotheses[:5],
            }
        )
    if derived_indices:
        blocks.append(
            {
                "kind": "indices",
                "title": "Интегральные и расчётные индексы",
                "items": [f"{x['name']}: {x['value']} — {x['interpretation']}" for x in derived_indices],
            }
        )
    blocks.append(
        {
            "kind": "strategy",
            "title": "Общая стратегия",
            "items": aggregate_clinical["strategy"][:3],
        }
    )
    blocks.append(
        {
            "kind": "limitations",
            "title": "Ограничения интерпретации",
            "items": aggregate_clinical["limitations"][:3],
        }
    )
    blocks.append({"kind": "urgent", "title": "Когда срочно", "items": [when_urgent]})

    professional_sections: List[str] = []
    professional_sections.append("## Главный вывод\n- Основной приоритет: " + main_priority)
    if secondary:
        professional_sections.append("## Вторичные находки\n- " + "\n- ".join(secondary[:3]))
    professional_sections.append(
        "## Матрица по документам\n"
        + "\n".join(
            [
                f"- {row['document']} | {row['biomaterial']} | {row['main_conclusion']} | Приоритет: {row['priority']}"
                for row in matrix_rows
            ]
        )
    )
    professional_sections.append("## Зоны внимания\n- " + "\n- ".join(attention_zones[:8]))
    professional_sections.append("## Что не подтверждается\n- " + "\n- ".join(not_supported[:6]))
    if derived_indices:
        professional_sections.append(
            "## Интегральные и расчётные индексы\n- "
            + "\n- ".join([f"{x['name']}: {x['value']} ({x['interpretation']})" for x in derived_indices])
        )
    if diagnostics:
        professional_sections.append("## Что проверить дальше\n- " + "\n- ".join(diagnostics[:10]))
    if working_hypotheses:
        professional_sections.append("## Рабочие гипотезы (не диагнозы)\n- " + "\n- ".join(working_hypotheses[:5]))
    professional_sections.append("## Общая стратегия\n- " + "\n- ".join(aggregate_clinical["strategy"][:3]))
    professional_sections.append("## Ограничения интерпретации\n- " + "\n- ".join(aggregate_clinical["limitations"][:3]))
    professional_sections.append("## Когда срочно\n- " + when_urgent)
    aggregate_professional = "\n\n".join(professional_sections)

    aggregate_result: Dict[str, Any] = {
        "case_summary": _safe_case_summary(case_summary),
        "severity_index": "GREEN",
        "safe_next_steps": safe_next_steps,
        "when_urgent": when_urgent,
        "confidence": "Medium",
        "disclaimer": DISCLAIMER_TEXT,
        "educational_disclaimer": METABOLIC_EDU_DISCLAIMER,
        "user_summary": _safe_aggregate_short(user_summary, 560),
        "display_summary": display_summary,
        "professional_summary": aggregate_professional,
        "pattern_main_conclusion": merged_pm,
        "pattern_summary_headline": merged_ph,
        "clinical_patterns_merged": merged_clinical_patterns[:32],
        "aggregate_document_sections": aggregate_document_sections,
        "aggregate_clinical": aggregate_clinical,
        "summary": {
            "title": aggregate_clinical["title"],
            "main_priority": aggregate_clinical["main_conclusion"]["main_priority"],
            "secondary_findings": aggregate_clinical["main_conclusion"]["secondary_findings"],
        },
        "risks": aggregate_clinical["attention_zones"][:8],
        "actions": (
            checks_grouped["high"][:5]
            + checks_grouped["medium"][:5]
            + checks_grouped["optional"][:5]
        ),
        "analyses": aggregate_clinical["document_matrix"],
        "conclusions": _dedup([main_priority] + secondary[:2], limit=4),
        "diagnosis_hints": [],
        "treatment": [],
        "nutrition": [],
        "activity": [],
        "prevention": [],
        "extracted_text": "\n\n".join(str(d.get("extracted_text") or "")[:2000] for d in docs if str(d.get("extracted_text") or "").strip()),
        "document_name": case_name,
        "document_type": "aggregate_clinical_report",
        "modern_evidence": [],
        "evidence_links": [],
        "profile_context": _profile_clinical_context(profile)["profile_lines"],
        "profile_cautions": _profile_clinical_context(profile)["caution_lines"],
        "medication_warnings": [],
        "input_data": [str(d.get("filename") or "document") for d in docs],
        "findings": attention_zones[:10],
        "hypotheses": hypotheses,
        "diagnosis": [],
        "treatment_plan": [],
        "medications": [],
        "alternative_treatment": [],
        "physical_exercises": [],
        "diagnostics": diagnostics,
        "evidence_notes": [],
        "evidence_sources": [],
        "medical_reasoning": {},
        "metabolic_sections": {},
        "metabolic_overview": attention_zones[:8],
        "metabolite_tables": {},
        "thematic_metabolite_sections": {},
        "grouped_hypotheses": {},
        "unified_recommendations": {},
        "glossary_terms": [],
        "compact_for_doctor": bool(compact_for_doctor),
        "user_report_structured": {
            "severity": "normal",
            "headline": "Сводный клинический отчёт по нескольким лабораторным исследованиям",
            "blocks": blocks,
        },
        "user_report_text": _safe_aggregate_short(user_summary, 560),
        "user_hypotheses": [],
        "debug_user_report": {
            "documents_count": len(docs),
            "aggregate_type": "aggregate_clinical_report",
        },
    }
    _merged_pat = _merge_patient_meta_from_reports(single_reports)
    aggregate_result["patient"] = _merged_pat
    aggregate_result["sex"] = _merged_pat.get("sex")
    aggregate_result["age"] = _merged_pat.get("age_years")
    _agg_ctx = _profile_clinical_context(profile, lab_patient=_merged_pat)
    aggregate_result["profile_context"] = _agg_ctx["profile_lines"]
    aggregate_result["profile_cautions"] = _agg_ctx["caution_lines"]
    aggregate_result["physician_report_html"] = build_aggregate_physician_report_html(aggregate_result, single_reports) or ""
    try:
        from app.services.gold_standard_report import (
            build_gold_standard_for_aggregate,
            merge_gold_into_user_structured,
        )

        ur = aggregate_result["user_report_structured"]
        aggregate_result["user_report_structured"] = merge_gold_into_user_structured(
            ur, build_gold_standard_for_aggregate(aggregate_result)
        )
    except Exception:
        pass
    return aggregate_result


# ---------------------------------------------------------
# consultation flow (consultation_assistant)
# ---------------------------------------------------------


def build_consultation_final_report(
    *,
    case_summary: str,
    severity: str,
    structured: dict[str, Any] | None,
    orchestrator_state: dict[str, Any] | None,
    title: str | None = None,
) -> dict[str, Any]:
    """Итоговый отчёт консультации (пациент + врач)."""

    def _format_list(items: List[str], prefix: str = "• ") -> str:
        if not items:
            return ""
        return "\n".join(prefix + s for s in items)

    def _user_summary_from_parts(safe_next_steps: str, when_urgent: str) -> str:
        parts: List[str] = []
        if safe_next_steps:
            parts.append(safe_next_steps)
        if when_urgent:
            parts.append("В срочных случаях: " + when_urgent)
        return " ".join(parts) if parts else "Рекомендуется показаться врачу."

    def _display_summary(user_summary: str, safe_next_steps: str, when_urgent: str) -> str:
        s = str(user_summary or "").strip()
        if s:
            return s
        return _user_summary_from_parts(str(safe_next_steps or "").strip(), str(when_urgent or "").strip())

    structured = structured if isinstance(structured, dict) else {}
    state = orchestrator_state if isinstance(orchestrator_state, dict) else {}
    reasoning = structured.get("medical_reasoning") if isinstance(structured.get("medical_reasoning"), dict) else {}

    def _clean(items: list[str] | None, limit: int = 6) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for x in items or []:
            s = str(x or "").strip()
            if not s:
                continue
            low = s.lower()
            if low in seen:
                continue
            seen.add(low)
            out.append(s)
            if len(out) >= limit:
                break
        return out

    top_hypotheses = structured.get("top_hypotheses") or []
    hypotheses: list[str] = []
    leading = (reasoning.get("leading_hypothesis") or {}).get("label") if reasoning else ""
    if str(leading or "").strip():
        hypotheses.append(str(leading).strip())
    for item in reasoning.get("differential_list") or []:
        if isinstance(item, dict) and item.get("label"):
            lbl = str(item.get("label") or "").strip()
            if lbl and lbl not in hypotheses:
                hypotheses.append(lbl)
    for item in top_hypotheses:
        if isinstance(item, dict) and item.get("name"):
            label = str(item.get("name") or "").strip()
            likelihood = str(item.get("likelihood") or "").strip()
            if likelihood:
                label += f" ({likelihood})"
            if label and label not in hypotheses:
                hypotheses.append(label)

    diagnostics = _clean(
        (structured.get("recommended_labs") or state.get("suggested_labs") or [])
        + [str(x).strip() for x in (reasoning.get("must_ask_next") or []) if str(x).strip()],
        limit=8,
    )
    care_plan = _clean(
        (structured.get("care_plan_today") or [])
        + [str(x).strip() for x in (reasoning.get("safe_actions_now") or []) if str(x).strip()],
        limit=8,
    )
    when_urgent_items = _clean(
        (structured.get("when_urgent") or [])
        + [str(x).strip() for x in (reasoning.get("when_to_escalate") or []) if str(x).strip()]
        + [str(x).strip() for x in (reasoning.get("red_flags_detected") or []) if str(x).strip()],
        limit=6,
    )
    nutrition = _clean(state.get("nutrition_recommendations") or [], limit=6)
    activity = _clean(state.get("physical_exercise_prevention_rehabilitation") or [], limit=6)

    safe_next_steps_parts: list[str] = []
    if care_plan:
        safe_next_steps_parts.append("Что делать сегодня: " + "; ".join(care_plan[:3]))
    if diagnostics:
        safe_next_steps_parts.append("Что проверить дополнительно: " + "; ".join(diagnostics[:2]))
    safe_next_steps = " ".join(safe_next_steps_parts).strip() or (
        "Наблюдать динамику и обратиться к врачу при сохранении симптомов."
    )

    when_urgent = (
        "; ".join(when_urgent_items)
        if when_urgent_items
        else (
            "При появлении красных флагов (боль в груди, признаки инсульта, потеря сознания, "
            "сильная боль в животе, одышка и т.д.) — срочно обратитесь за помощью."
        )
    )

    professional_parts = [
        "Анамнез/жалобы: " + str(case_summary or "Консультация по жалобам и контексту."),
        "Индекс тяжести: " + str(severity or "YELLOW"),
    ]
    if hypotheses:
        professional_parts.append("Рабочие гипотезы:\n" + _format_list(hypotheses))
    if care_plan:
        professional_parts.append("Лечение / тактика:\n" + _format_list(care_plan))
    if diagnostics:
        professional_parts.append("Дообследование:\n" + _format_list(diagnostics))
    if nutrition:
        professional_parts.append("Питание:\n" + _format_list(nutrition))
    if activity:
        professional_parts.append("Физическая активность / реабилитация:\n" + _format_list(activity))
    professional_parts.append("Срочно:\n" + _format_list(when_urgent_items or [when_urgent]))
    professional_parts.append("Дисклеймер: " + DISCLAIMER_TEXT)

    short_findings = str(structured.get("patient_summary") or "").strip()
    if not short_findings and leading:
        short_findings = "Наиболее вероятно: " + str(leading).strip()
    user_parts = [
        "Краткий итог: " + (short_findings or "По текущим данным нужен контроль симптомов в динамике."),
        "Что делать: " + ("; ".join(care_plan[:3]) if care_plan else "Щадящий режим и наблюдение."),
        "Что проверить: "
        + (
            "; ".join(diagnostics[:2])
            if diagnostics
            else "Пока без расширенной диагностики, если нет red flags."
        ),
        "Когда быстрее к врачу: " + when_urgent,
    ]
    if nutrition:
        user_parts.append("Питание: " + "; ".join(nutrition[:2]))
    if activity:
        user_parts.append("Активность: " + "; ".join(activity[:2]))
    consultation_user_summary = " ".join([p for p in user_parts if p]).strip()

    return {
        "title": title or "Итог консультации",
        "case_summary": str(case_summary or "Консультация по жалобам и контексту."),
        "severity_index": str(severity or "YELLOW"),
        "safe_next_steps": safe_next_steps,
        "when_urgent": when_urgent,
        "confidence": "Medium",
        "disclaimer": DISCLAIMER_TEXT,
        "user_summary": consultation_user_summary,
        "display_summary": _display_summary(consultation_user_summary, safe_next_steps, when_urgent),
        "professional_summary": "\n\n".join([p for p in professional_parts if p]).strip(),
        "hypotheses": hypotheses,
        "diagnostics": diagnostics,
        "treatment": care_plan,
        "alternative_treatment": [],
        "nutrition": nutrition,
        "activity": activity,
        "prevention": activity,
        "structured_consultation": structured,
        "orchestrator_state": state,
    }
