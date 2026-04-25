"""
Gated/hidden channel: low-confidence hypotheses, confirmation-dependent content, internal reasoning.
Не показывается пациенту до подтверждения; может использоваться для «Отчёт для врача» или внутреннего аудита.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.clinical_engine.contracts import ClinicalCoreResult, Finding


def _hypothesis_confidence(hypothesis: str) -> str:
    """Эвристика: гипотезы с «возможна», «не исключена» — medium/low для gating."""
    h = hypothesis.lower()
    if "возможн" in h and ("семейн" in h or "первичн" in h or "гиперхолестеринеми" in h):
        return "low"
    if "возможн" in h or "не исключен" in h:
        return "medium"
    return "high"


def build_gated_payload(core: ClinicalCoreResult) -> Dict[str, Any]:
    """
    Секции и гипотезы, которые не показываются пациенту сразу:
    low-confidence hypotheses, confirmation-dependent content, краткое internal reasoning.
    """
    gated_hypotheses: List[str] = []
    gated_reasoning: List[str] = []
    gated_sections: List[Dict[str, Any]] = []

    for h in core.working_hypotheses or []:
        conf = _hypothesis_confidence(h)
        if conf in ("low", "medium"):
            gated_hypotheses.append(h)
            gated_reasoning.append(f"Гипотеза (уверенность: {conf}): {h}")

    # Findings с requires_gating или low confidence
    for f in core.final_findings or []:
        if getattr(f, "requires_gating", None) is True:
            gated_sections.append({
                "type": "finding",
                "code": f.code,
                "title": f.title,
                "reason": "requires_confirmation",
            })
        if (getattr(f, "confidence", None) or "").lower() == "low":
            gated_reasoning.append(f"Finding {f.code}: low confidence")

    if core.risk:
        gated_sections.append({
            "type": "risk_detail",
            "domain": core.risk.primary_domain,
            "level": core.risk.overall_level,
            "summary": core.risk.summary_text[:200] + "..." if len(core.risk.summary_text or "") > 200 else (core.risk.summary_text or ""),
        })

    return {
        "gated_hypotheses": gated_hypotheses,
        "gated_reasoning": gated_reasoning,
        "gated_sections": gated_sections,
    }
