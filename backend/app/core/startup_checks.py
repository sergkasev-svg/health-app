"""
Стартовые проверки: config, db, storage, queue, директории, предупреждение admin token в prod.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Tuple

from app.core.settings import get_settings

logger = logging.getLogger(__name__)
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


def run_startup_checks() -> Tuple[bool, List[str]]:
    """
    Выполняет проверки при старте. Возвращает (all_ok, list of warnings/errors).
    Критичные ошибки логируются; приложение может стартовать в degraded.
    """
    warnings: List[str] = []
    critical = False

    try:
        settings = get_settings()
    except Exception as e:
        logger.error("startup_check_config_failed", extra={"error": str(e)})
        return False, [f"Config invalid: {e}"]

    # DB (optional)
    if settings.DATABASE_URL:
        try:
            # placeholder: реальный ping
            pass
        except Exception as e:
            warnings.append(f"Database unreachable: {e}")
            critical = True  # если в проде нужна БД

    # Storage path writable
    if (settings.FILE_STORAGE_MODE or "").lower() == "local":
        path = Path(settings.FILE_STORAGE_PATH) if settings.FILE_STORAGE_PATH else _BACKEND_DIR / "data"
        try:
            path.mkdir(parents=True, exist_ok=True)
            (path / ".startup_check").write_text("ok")
        except Exception as e:
            warnings.append(f"Storage path not writable: {path} — {e}")
            # не critical: можно работать без файлового хранилища в минимальном режиме

    # Queue mode valid
    mode = (settings.QUEUE_MODE or "sync").lower()
    if mode not in ("sync", "disabled", "celery", "rq"):
        warnings.append(f"Unknown QUEUE_MODE: {mode}; using sync")

    # Critical dirs
    for name in ["data", "data/users"]:
        d = _BACKEND_DIR / name
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            warnings.append(f"Cannot create directory {d}: {e}")

    # Admin token in prod
    if (settings.APP_ENV or "").lower() == "prod":
        admin_token = settings.ADMIN_TOKEN or os.environ.get("ADMIN_QUALITY_TOKEN", "").strip()
        if admin_token:
            warnings.append("Production uses ADMIN_TOKEN/ADMIN_QUALITY_TOKEN fallback; prefer JWT with admin role")

    return not critical, warnings
