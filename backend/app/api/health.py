"""
Health endpoints: /health/live, /health/ready, /health/deps.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter

from app.core.settings import get_settings

router = APIRouter(prefix="/health", tags=["health"])

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_DATA_ROOT = _BACKEND_DIR / "data"


@router.get("/live")
def health_live() -> Dict[str, str]:
    """Liveness: приложение живо. Минимальная проверка."""
    return {"status": "ok"}


@router.get("/ready")
def health_ready() -> Dict[str, Any]:
    """
    Readiness: приложение готово принимать трафик.
    Может быть degraded при недоступности второстепенных сервисов.
    """
    deps = health_deps()
    checks = deps.get("checks", {})
    all_ok = checks.get("config", True)
    db_ok = checks.get("database", True)
    storage_ok = checks.get("storage", True)
    queue_ok = checks.get("queue", True)
    ready = all_ok and (db_ok or not get_settings().DATABASE_URL)  # db optional
    return {
        "status": "ready" if ready else "degraded",
        "checks": checks,
    }


@router.get("/deps")
def health_deps() -> Dict[str, Any]:
    """Зависимости: config, db, storage, queue."""
    settings = get_settings()
    checks: Dict[str, Any] = {}

    # config
    try:
        _ = settings.APP_ENV
        checks["config"] = True
    except Exception as e:
        checks["config"] = False
        checks["config_error"] = str(e)

    # database (optional)
    if settings.DATABASE_URL:
        try:
            # placeholder: реальный ping к БД
            checks["database"] = True
        except Exception as e:
            checks["database"] = False
            checks["database_error"] = str(e)
    else:
        checks["database"] = None  # not used

    # storage (local path writable)
    if settings.FILE_STORAGE_MODE == "local":
        try:
            root = Path(settings.FILE_STORAGE_PATH) if settings.FILE_STORAGE_PATH else _DATA_ROOT
            root.mkdir(parents=True, exist_ok=True)
            (root / ".health").write_text("ok")
            checks["storage"] = True
        except Exception as e:
            checks["storage"] = False
            checks["storage_error"] = str(e)
    elif settings.FILE_STORAGE_MODE == "disabled":
        checks["storage"] = None
    else:
        checks["storage"] = True  # s3-like: assume ok

    # queue
    try:
        mode = (settings.QUEUE_MODE or "sync").lower()
        checks["queue"] = mode in ("sync", "disabled", "celery", "rq")
    except Exception as e:
        checks["queue"] = False
        checks["queue_error"] = str(e)

    return {"checks": checks}
