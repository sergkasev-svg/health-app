"""
Политики хранения: TTL для экспортов, аудит-логов, временных файлов, сессий.
Хелперы очистки.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_DATA_ROOT = _BACKEND_DIR / "data"

# TTL в секундах (или днях, переведённые в секунды)
TEMP_EXPORT_TTL_DAYS = 7
AUDIT_RETENTION_DAYS = 90
QUALITY_LOGS_RETENTION_DAYS = 60
TEMP_FILES_TTL_DAYS = 3
DEBUG_ARTIFACTS_TTL_DAYS = 1


def cleanup_expired_exports() -> int:
    """Удаляет экспорты старше TEMP_EXPORT_TTL_DAYS. Возвращает количество удалённых."""
    removed = 0
    cutoff = time.time() - (TEMP_EXPORT_TTL_DAYS * 24 * 3600)
    for sub in ("private/exports", "exports"):
        d = _DATA_ROOT / sub
        if not d.is_dir():
            continue
        for f in d.rglob("*"):
            if f.is_file() and f.stat().st_mtime < cutoff:
                try:
                    f.unlink()
                    removed += 1
                except Exception as e:
                    logger.warning("cleanup_export_failed", extra={"path": str(f), "error": str(e)})
    return removed


def cleanup_old_temp_files() -> int:
    """Удаляет временные файлы старше TEMP_FILES_TTL_DAYS."""
    removed = 0
    cutoff = time.time() - (TEMP_FILES_TTL_DAYS * 24 * 3600)
    for name in ("tmp", "temp", "uploads"):
        d = _DATA_ROOT / name
        if not d.is_dir():
            continue
        for f in d.rglob("*"):
            if f.is_file() and f.stat().st_mtime < cutoff:
                try:
                    f.unlink()
                    removed += 1
                except Exception as e:
                    logger.warning("cleanup_temp_failed", extra={"path": str(f), "error": str(e)})
    return removed


def cleanup_old_logs() -> int:
    """Ротация/очистка старых логов (audit, quality)."""
    removed = 0
    audit_dir = _DATA_ROOT / "audit"
    if audit_dir.is_dir():
        cutoff = time.time() - (AUDIT_RETENTION_DAYS * 24 * 3600)
        for f in audit_dir.glob("*.jsonl"):
            if f.stat().st_mtime < cutoff:
                try:
                    f.unlink()
                    removed += 1
                except Exception as e:
                    logger.warning("cleanup_audit_log_failed", extra={"path": str(f), "error": str(e)})
    return removed


def cleanup_old_debug_artifacts() -> int:
    """Удаляет отладочные артефакты старше DEBUG_ARTIFACTS_TTL_DAYS."""
    removed = 0
    cutoff = time.time() - (DEBUG_ARTIFACTS_TTL_DAYS * 24 * 3600)
    debug_dir = _DATA_ROOT / "debug"
    if debug_dir.is_dir():
        for f in debug_dir.rglob("*"):
            if f.is_file() and f.stat().st_mtime < cutoff:
                try:
                    f.unlink()
                    removed += 1
                except Exception as e:
                    logger.warning("cleanup_debug_failed", extra={"path": str(f), "error": str(e)})
    return removed
