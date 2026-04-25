"""
Реестр фоновых задач: имена и обработчики для task_queue.
Экспорт PDF, снимки качества, парсинг, очистка.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from app.services.task_queue import register_task

logger = logging.getLogger(__name__)


def _export_physician_report_pdf(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Задача: экспорт врачебного отчёта в PDF."""
    from app.services.report_export_service import ReportExportService
    svc = ReportExportService()
    return svc.export_physician_report_sync(
        report_text=payload.get("report_text", ""),
        user_id=payload.get("user_id", ""),
        report_id=payload.get("report_id"),
    )


def _export_user_report_pdf(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Задача: экспорт пользовательского отчёта в PDF."""
    from app.services.report_export_service import ReportExportService
    svc = ReportExportService()
    return svc.export_user_report_sync(
        report_text=payload.get("report_text", ""),
        user_id=payload.get("user_id", ""),
        report_id=payload.get("report_id"),
    )


def _rebuild_quality_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Задача: пересборка снимка качества для админки."""
    try:
        from app.services.admin_analytics_service import AdminAnalyticsService
        days = payload.get("days", 7)
        svc = AdminAnalyticsService()
        snapshot = svc.build_dashboard_snapshot(days)
        return {"ok": True, "days": days}
    except Exception as e:
        logger.exception("rebuild_quality_snapshot_failed")
        return {"ok": False, "error": str(e)}


def _generate_weekly_quality_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Задача: еженедельный отчёт по качеству."""
    try:
        from app.services.weekly_quality_report import WeeklyQualityReportService
        days = payload.get("days", 7)
        svc = WeeklyQualityReportService()
        report = svc.build_report(days)
        return {"ok": True, "days": days}
    except Exception as e:
        logger.exception("generate_weekly_quality_report_failed")
        return {"ok": False, "error": str(e)}


def _deep_document_parse(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Задача: глубокий парсинг документа (тяжёлый)."""
    # Placeholder: в реальности вызвать document_extraction с полным парсингом
    return {"ok": True, "placeholder": True}


def _cleanup_temp_files(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Задача: очистка временных файлов."""
    try:
        from app.services.data_retention_policy import cleanup_old_temp_files
        cleanup_old_temp_files()
        return {"ok": True}
    except Exception as e:
        logger.warning("cleanup_temp_files_failed", extra={"error": str(e)})
        return {"ok": False, "error": str(e)}


def _rotate_logs_task(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Задача: ротация логов (placeholder)."""
    return {"ok": True, "placeholder": True}


def _knowledge_enrichment_followup(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Задача: обогащение по теме консультации (индекс + снимок для ревью)."""
    from app.services.knowledge_enrichment_queue import process_knowledge_enrichment_job

    return process_knowledge_enrichment_job(payload)


def _knowledge_enrichment_seed_batch(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Задача: постановка тем из knowledge_refresh_seed_topics.txt в очередь обогащения."""
    from app.services.knowledge_enrichment_queue import run_seed_batch_enrichment

    mt = payload.get("max_topics", 20)
    try:
        n = int(mt) if mt is not None else 20
    except (TypeError, ValueError):
        n = 20
    return run_seed_batch_enrichment(max_topics=n)


def _knowledge_index_merge_flywheel(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Задача: merge approved flywheel → chunks.json."""
    from app.services.knowledge_index_merge import merge_approved_flywheel_into_chunks

    mi = payload.get("max_items", 25)
    try:
        n = int(mi) if mi is not None else 25
    except (TypeError, ValueError):
        n = 25
    return merge_approved_flywheel_into_chunks(max_new=n)


def _knowledge_enrichment_daily_clusters(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Задача: очередь enrichment по слабым жалобам/кластерам из runtime analytics."""
    from app.services.knowledge_enrichment_queue import run_daily_cluster_enrichment_from_analytics

    mt = payload.get("max_topics", 8)
    try:
        n = int(mt) if mt is not None else 8
    except (TypeError, ValueError):
        n = 8
    return run_daily_cluster_enrichment_from_analytics(max_topics=n)


def register_background_tasks() -> None:
    """Регистрирует все фоновые задачи в task_queue."""
    register_task("export_physician_report_pdf", _export_physician_report_pdf)
    register_task("export_user_report_pdf", _export_user_report_pdf)
    register_task("rebuild_quality_snapshot", _rebuild_quality_snapshot)
    register_task("generate_weekly_quality_report", _generate_weekly_quality_report)
    register_task("deep_document_parse", _deep_document_parse)
    register_task("cleanup_temp_files", _cleanup_temp_files)
    register_task("rotate_logs_task", _rotate_logs_task)
    register_task("knowledge_enrichment_followup", _knowledge_enrichment_followup)
    register_task("knowledge_enrichment_seed_batch", _knowledge_enrichment_seed_batch)
    register_task("knowledge_index_merge_flywheel", _knowledge_index_merge_flywheel)
    register_task("knowledge_enrichment_daily_clusters", _knowledge_enrichment_daily_clusters)
