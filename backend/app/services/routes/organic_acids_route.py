"""
Процессор маршрута organic_acids: обёртка над существующим document_routes pipeline.
Не смешивать с UTI / histamine / food triggers — см. clinical_route_conflicts.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.document_routes.organic_acids_route import build_organic_acids_report


class OrganicAcidsRouteProcessor:
    """Извлечение и форматирование отчёта по органическим кислотам."""

    def process(self, document_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        document_data: как минимум extracted_text, filename; опционально profile.
        context: опционально raw_hypotheses и др.
        """
        ctx = context or {}
        doc = {
            "filename": document_data.get("filename") or "документ",
            "extracted_text": (document_data.get("extracted_text") or document_data.get("text") or "").strip(),
        }
        if not doc["extracted_text"]:
            return {"ok": False, "error": "no_extracted_text", "report": {}}

        report = build_organic_acids_report(
            doc,
            profile=document_data.get("profile") or ctx.get("profile"),
            raw_hypotheses=ctx.get("raw_hypotheses"),
        )
        if not report:
            return {"ok": False, "error": "not_organic_acids_or_parse_failed", "report": {}}

        return {
            "ok": True,
            "primary_route": "organic_acids_route",
            "report": report,
            "physician_report_html": report.get("physician_report_html"),
            "summary_lines": report.get("summary") or [],
            "abnormal_count": len(report.get("abnormal_markers_table") or []),
        }
