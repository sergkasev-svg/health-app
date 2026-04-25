"""
Экспорт отчётов в PDF: physician, user, combined.
Очередь при включении, sync fallback; private storage; метаданные job.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from app.core.settings import get_settings
from app.services.audit_logger import log_audit_event
from app.services.storage_service import StorageService
from app.services.task_queue import enqueue_task, get_task_status, run_task_sync

logger = logging.getLogger(__name__)


def _make_pdf_from_text(text: str) -> bytes:
    """Минимальный PDF из текста (reportlab, встроенный шрифт)."""
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    style = styles["Normal"]
    parts = []
    for line in (text or "").split("\n"):
        line = (line or "").strip()
        if not line:
            parts.append(Spacer(1, 4))
            continue
        safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts.append(Paragraph(safe, style))
    doc.build(parts)
    return buf.getvalue()


class ReportExportService:
    """Экспорт отчётов: physician, user, combined; queue или sync; private storage."""

    def __init__(self) -> None:
        self._storage = StorageService()
        self._settings = get_settings()

    def export_physician_report(
        self,
        report_text: str,
        user_id: str,
        report_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Экспорт врачебного отчёта. При очереди — job_id; иначе сразу результат."""
        if not self._settings.PDF_EXPORT_ENABLED:
            return {"ok": False, "error": "PDF export disabled", "job_id": None}
        use_queue = self._settings.REPORT_EXPORT_QUEUE_ENABLED
        payload = {"report_text": report_text, "user_id": user_id, "report_id": report_id or str(uuid.uuid4()), **kwargs}
        if use_queue:
            out = enqueue_task("export_physician_report_pdf", payload)
            return {"ok": True, "job_id": out.get("task_id"), "status": out.get("status", "queued")}
        result = self.export_physician_report_sync(**payload)
        if result.get("ok"):
            log_audit_event("export_physician_report", target_type="report", target_id=report_id, actor_user_id=user_id, metadata={"key": result.get("key")})
        return {"ok": result.get("ok", False), "job_id": None, "status": "completed", "key": result.get("key")}

    def export_physician_report_sync(
        self,
        report_text: str,
        user_id: str,
        report_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Синхронный экспорт врачебного отчёта в PDF; сохраняет в private storage."""
        try:
            pdf_bytes = _make_pdf_from_text(report_text or "")
            key = self._storage.save_private_file(
                pdf_bytes,
                prefix=f"exports/physician/{user_id}",
                extension=".pdf",
            )
            return {"ok": True, "key": key}
        except Exception as e:
            logger.exception("export_physician_report_sync_failed")
            return {"ok": False, "error": str(e)}

    def export_user_report(
        self,
        report_text: str,
        user_id: str,
        report_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Экспорт пользовательского отчёта. Аналогично physician."""
        if not self._settings.PDF_EXPORT_ENABLED:
            return {"ok": False, "error": "PDF export disabled", "job_id": None}
        use_queue = self._settings.REPORT_EXPORT_QUEUE_ENABLED
        payload = {"report_text": report_text, "user_id": user_id, "report_id": report_id or str(uuid.uuid4()), **kwargs}
        if use_queue:
            out = enqueue_task("export_user_report_pdf", payload)
            return {"ok": True, "job_id": out.get("task_id"), "status": out.get("status", "queued")}
        result = self.export_user_report_sync(**payload)
        if result.get("ok"):
            log_audit_event("export_user_report", target_type="report", target_id=report_id, actor_user_id=user_id, metadata={"key": result.get("key")})
        return {"ok": result.get("ok", False), "job_id": None, "status": "completed", "key": result.get("key")}

    def export_user_report_sync(
        self,
        report_text: str,
        user_id: str,
        report_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        try:
            pdf_bytes = _make_pdf_from_text(report_text or "")
            key = self._storage.save_private_file(
                pdf_bytes,
                prefix=f"exports/user/{user_id}",
                extension=".pdf",
            )
            return {"ok": True, "key": key}
        except Exception as e:
            logger.exception("export_user_report_sync_failed")
            return {"ok": False, "error": str(e)}

    def export_combined_case_pack(
        self,
        physician_text: str,
        user_text: str,
        user_id: str,
        case_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Объединённый пакет: physician + user отчёт в одном PDF (или два файла)."""
        if not self._settings.PDF_EXPORT_ENABLED:
            return {"ok": False, "error": "PDF export disabled"}
        combined = f"=== Врачебный отчёт ===\n\n{physician_text or ''}\n\n=== Пользовательский отчёт ===\n\n{user_text or ''}"
        return self.export_user_report(combined, user_id, report_id=case_id)

    def get_export_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Статус экспорта по job_id (если использовалась очередь)."""
        return get_task_status(job_id)
