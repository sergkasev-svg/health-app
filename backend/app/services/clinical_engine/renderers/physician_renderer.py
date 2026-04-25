"""
Рендер отчёта для врача: precision-first, полные формулировки, гипотезы, risk, next steps.
Строится только из ClinicalCoreResult — единый источник правды.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.clinical_engine.contracts import ClinicalCoreResult, Finding, LabValue
from app.services.clinical_engine.presentation.physician_style import PHYSICIAN_SECTION_TITLES
from app.services.clinical_engine.text_templates import get_report_title_subtitle

DISPLAY_LABELS: Dict[str, str] = {
    "ldl_cholesterol": "ЛПНП",
    "total_cholesterol": "Общий холестерин",
    "hdl_cholesterol": "ЛПВП",
    "triglycerides": "Триглицериды",
    "hba1c": "HbA1c",
    "fructosamine": "Фруктозамин",
    "hs_crp": "hs-CRP",
    "crp": "С-реактивный белок",
    "homocysteine": "Гомоцистеин",
    "lp_a": "Липопротеин (а)",
    "apo_a1": "Аполипопротеин A1",
    "apo_b": "Аполипопротеин B",
}


def _primary_lab_value(f: Finding, values_list: List[LabValue]) -> Optional[LabValue]:
    code = f.primary_value_code
    if code:
        for v in values_list:
            if v.code == code:
                return v
    for code in f.supporting_markers or []:
        for v in values_list:
            if v.code == code:
                return v
    return None


def render_physician_report(core: ClinicalCoreResult, filename: str = "") -> Dict[str, Any]:
    """
    Строит physician report (legacy-совместимый dict) из единого core.
    Сохраняет клиническую точность, профессиональные формулировки, гипотезы, risk.
    """
    values_list = list(core.normalized_values.values()) if core.normalized_values else []
    title, subtitle = get_report_title_subtitle(core.document_type, core.profile)
    report_title = PHYSICIAN_SECTION_TITLES["report_title"]
    report_subtitle = title or subtitle or "Структурированная интерпретация биохимического анализа крови"

    abnormal = []
    for f in core.final_findings:
        pv = _primary_lab_value(f, values_list)
        if pv is not None:
            val_str = str(pv.value) if pv.value is not None else (", ".join(f.related_values) if f.related_values else "")
            ref_low = str(pv.ref_low) if pv.ref_low is not None else ""
            ref_high = str(pv.ref_high) if pv.ref_high is not None else ""
            direction = "high" if pv.status in ("high", "borderline_high", "critical") else "low" if pv.status in ("low", "borderline_low") else "normal"
            if direction == "normal" and f.severity in ("high", "moderate"):
                direction = "high"
            elif direction == "normal" and f.severity == "mild" and "фруктозамин" in (f.title or "").lower():
                direction = "high"
        else:
            val_str = ", ".join(f.related_values) if f.related_values else (f.summary_text or "")[:50]
            ref_low = ref_high = ""
            direction = "high" if f.severity in ("high", "moderate") else "low"
        abnormal.append({
            "marker": f.title,
            "value": val_str or (f.summary_text or "")[:50],
            "ref_low": ref_low,
            "ref_high": ref_high,
            "direction": direction,
            "comment": f.physician_comment,
        })

    # Единственный источник «Краткого вывода» для UI: pattern layer (не сырой summary модели).
    pm = (getattr(core, "pattern_main_conclusion", None) or "").strip()
    ph = (getattr(core, "pattern_summary_headline", None) or "").strip()
    pat_att = [str(x).strip() for x in (getattr(core, "pattern_attention_items", None) or []) if str(x).strip()]
    pat_ns = [str(x).strip() for x in (getattr(core, "pattern_next_steps_items", None) or []) if str(x).strip()]

    if pm:
        summary_lines = [pm]
        brief_text = pm
    elif core.summary:
        summary_lines = [core.summary]
        brief_text = core.summary
    else:
        summary_lines = []
        brief_text = ""
    followup = [
        {
            "direction": s.get("direction", ""),
            "check": s.get("check") or s.get("what", ""),
            "why": s.get("why", ""),
            "priority": s.get("priority", ""),
        }
        for s in core.next_steps
    ]
    hypotheses = [{"hypothesis": h, "basis": "", "comment": ""} for h in core.working_hypotheses]

    professional_parts = [
        report_title,
        report_subtitle,
        "",
        PHYSICIAN_SECTION_TITLES["brief_conclusion"],
        brief_text,
        "",
    ]
    if core.risk:
        professional_parts.append(PHYSICIAN_SECTION_TITLES["risk_assessment"])
        professional_parts.append(core.risk.summary_text)
        for d in (core.risk.domain_risks or [])[:1]:
            if getattr(d, "rationale", None):
                for r in d.rationale[:5]:
                    professional_parts.append(f"- {r}")
        professional_parts.append("")
    professional_parts.append(PHYSICIAN_SECTION_TITLES["key_findings"])
    for f in core.final_findings:
        professional_parts.append(f"- {f.title}: {f.summary_text}")
    professional_parts.append("")
    professional_parts.append(PHYSICIAN_SECTION_TITLES["hypotheses"])
    for h in core.working_hypotheses:
        professional_parts.append(f"- {h}")
    professional_parts.append("")
    professional_parts.append(PHYSICIAN_SECTION_TITLES["next_steps"])
    for s in core.next_steps:
        what = s.get("what") or s.get("check", "")
        professional_parts.append(f"- {what} ({s.get('why', '')})")
    professional_parts.append("")
    professional_parts.append(PHYSICIAN_SECTION_TITLES["limitations"])
    for lim in core.limitations:
        professional_parts.append(f"- {lim}")

    return {
        "doc_type": core.document_type,
        "document_type": core.document_type,
        "document_name": filename,
        "document_summary": {},
        "patient": {},
        "report_title": report_title,
        "report_subtitle": report_subtitle,
        "summary": summary_lines,
        "abnormal_findings": abnormal,
        "abnormal_markers_table": abnormal,
        "recommended_followup_table": followup,
        "top_hypotheses_table": hypotheses,
        "grouped_interpretation_table": [
            {
                "group": g.get("group", ""),
                "markers": [DISPLAY_LABELS.get(m, m) for m in g.get("markers", [])],
                "interpretation": g.get("interpretation", ""),
            }
            for g in core.group_interpretations
        ],
        "interpretation": summary_lines,
        "follow_up": {"tests": [s.get("what") or s.get("check", "") for s in core.next_steps], "referrals": [], "notes": []},
        "limitations": core.limitations,
        "recommendation_blocks": [],
        "professional_summary": "\n".join(professional_parts),
        "risk_assessment": core.risk.model_dump() if core.risk else None,
        "clinical_patterns": [p.model_dump() for p in (core.clinical_patterns or [])],
        "pattern_summary_headline": ph,
        "pattern_main_conclusion": pm,
        "pattern_attention_items": pat_att,
        "pattern_next_steps_items": pat_ns,
    }
