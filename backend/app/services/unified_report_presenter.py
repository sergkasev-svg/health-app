"""
Organic acids: полный lab-report dict поверх unified_lab_report_presenter.
Вся пользовательская/кейс-сводка собирается в unified_lab_report_presenter.py.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from app.services.clinical_oa_axis_routing import build_clinical_routing_output
from app.services.unified_lab_report_presenter import build_unified_lab_report_presenter


def _s(x: Any) -> str:
    return str(x or "").strip()


def _strip_html(text: str) -> str:
    s = str(text or "")
    s = re.sub(r"(?is)<script.*?>.*?</script>", " ", s)
    s = re.sub(r"(?is)<style.*?>.*?</style>", " ", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _safe_case_summary(text: str, fallback: str = "Клиническая сводка по загруженному документу.") -> str:
    s = _strip_html(text)
    if not s:
        return fallback
    if len(s) > 700:
        s = s[:700].rstrip()
        if " " in s:
            s = s.rsplit(" ", 1)[0]
        s = s.rstrip(",;:- ") + "…"
    return s


def _safe_professional_summary(text: str) -> str:
    return _strip_html(text)


def _dedup(items: List[str], max_items: int = 999) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items or []:
        s = _strip_html(_s(item))
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= max_items:
            break
    return out


def _extract_summary_lines(doc_physician: Dict[str, Any]) -> List[str]:
    return _dedup([_s(x) for x in (doc_physician.get("summary") or [])], max_items=6)


def _extract_hypotheses(doc_physician: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for h in doc_physician.get("top_hypotheses_table") or []:
        if isinstance(h, dict):
            val = _s(h.get("hypothesis"))
        else:
            val = _s(h)
        if val:
            out.append(val)
    return _dedup(out, max_items=5)


def build_unified_organic_acids_report(
    *,
    doc: Dict[str, Any],
    doc_physician: Dict[str, Any],
    profile_lines: List[str],
    caution_lines: List[str],
    compact_for_doctor: bool,
    disclaimer_text: str,
    educational_disclaimer: str,
) -> Dict[str, Any]:
    filename = _s(doc.get("filename")) or "документ"

    routed = build_clinical_routing_output(doc_physician)
    present = build_unified_lab_report_presenter(
        filename=filename,
        document_type="organic_acids_urine",
        physician_report=doc_physician,
        routing_output=routed,
    )

    doctor_view = routed.get("doctor") or {}
    summary_lines = _extract_summary_lines(doc_physician)
    hypotheses = _extract_hypotheses(doc_physician)
    dbg = present.get("presenter_debug") or {}
    diagnostics = list(dbg.get("follow_checks") or [])

    # Ленивый импорт: иначе цикл document_physician_report → organic_acids_route → presenter
    from app.services.document_physician_report import format_document_physician_report

    professional_summary = _safe_professional_summary(format_document_physician_report(doc_physician))

    routed_conclusions = _dedup([_s(x) for x in (doctor_view.get("routing_conclusions") or [])], max_items=5)
    conclusions = routed_conclusions or summary_lines[:5]

    case_summary = _safe_case_summary(
        str(present.get("case_summary") or "").strip(),
        fallback=f"Профиль органических кислот по документу {filename}.",
    )

    return {
        "case_summary": case_summary,
        "severity_index": "GREEN",
        "safe_next_steps": str(present.get("safe_next_steps") or "").strip(),
        "when_urgent": str(present.get("when_urgent") or "").strip(),
        "confidence": "Medium",
        "disclaimer": disclaimer_text,
        "educational_disclaimer": educational_disclaimer,
        "user_summary": str(present.get("user_summary") or "").strip(),
        "display_summary": str(present.get("display_summary") or "").strip(),
        "professional_summary": professional_summary,
        "physician_report_html": doc_physician.get("physician_report_html"),
        "conclusions": conclusions,
        "diagnosis_hints": [],
        "treatment": [],
        "nutrition": [],
        "activity": [],
        "prevention": [],
        "extracted_text": _s(doc.get("extracted_text")),
        "document_name": filename,
        "document_type": "organic_acids_urine",
        "modern_evidence": [],
        "evidence_links": [],
        "profile_context": profile_lines,
        "profile_cautions": caution_lines,
        "medication_warnings": [],
        "input_data": ["Документ: " + filename, "Органические кислоты в моче"],
        "findings": summary_lines[:8],
        "hypotheses": hypotheses[:5],
        "diagnosis": [],
        "treatment_plan": doc_physician.get("treatment_plan") or [],
        "treatment_plan_cta": doc_physician.get("treatment_plan_cta") or "",
        "medications": [],
        "alternative_treatment": [],
        "physical_exercises": [],
        "diagnostics": diagnostics,
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
        "debug_user_report": {
            "ranked_axes": routed.get("ranked_axes") or [],
            "routing_top_lines": doctor_view.get("routing_top_lines") or [],
            "presenter_debug": dbg,
        },
    }
