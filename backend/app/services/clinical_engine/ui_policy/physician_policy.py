"""
Physician-visible channel: full report, findings, hypotheses, risk details.
Всё, что нужно врачу для интерпретации; без упрощения.
"""
from __future__ import annotations

from typing import Any, Dict

from app.services.clinical_engine.contracts import ClinicalCoreResult
from app.services.clinical_engine.renderers.physician_renderer import render_physician_report


def build_physician_payload(core: ClinicalCoreResult, filename: str = "") -> Dict[str, Any]:
    """
    Полный physician report: summary, key findings, hypotheses, risk, next steps, limitations.
    Тот же core; подача профессиональная, без сокрытия.
    """
    return render_physician_report(core, filename)
