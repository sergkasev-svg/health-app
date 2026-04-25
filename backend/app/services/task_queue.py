"""
Очередь задач: enqueue_task, run_task_sync, get_task_status.
Режимы: sync (fallback), disabled, future celery/rq.
Emergency/core clinical response не ждёт очереди.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

_TASK_REGISTRY: Dict[str, callable] = {}
_SYNC_RESULTS: Dict[str, Dict[str, Any]] = {}


def run_task_sync(task_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Выполняет задачу синхронно. Fallback когда очередь отключена."""
    fn = _TASK_REGISTRY.get(task_name)
    if not fn:
        return {"ok": False, "error": f"Unknown task: {task_name}", "task_id": None}
    try:
        result = fn(payload)
        return {"ok": True, "result": result, "task_id": None}
    except Exception as e:
        logger.exception("task_sync_failed", extra={"task_name": task_name})
        return {"ok": False, "error": str(e), "task_id": None}


def enqueue_task(task_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ставит задачу в очередь или выполняет синхронно в зависимости от QUEUE_MODE.
    Возвращает { task_id, status }.
    """
    settings = get_settings()
    mode = (settings.QUEUE_MODE or "sync").lower()
    if mode in ("disabled", "sync"):
        out = run_task_sync(task_name, payload)
        task_id = str(uuid.uuid4()) if out.get("ok") else None
        return {"task_id": task_id, "status": "completed" if out.get("ok") else "failed"}
    # celery / rq: placeholder — в реальности отправить в broker
    task_id = str(uuid.uuid4())
    logger.info("enqueue_placeholder", extra={"task_id": task_id, "task_name": task_name, "queue_mode": mode})
    return {"task_id": task_id, "status": "queued"}


def get_task_status(task_id: str) -> Optional[Dict[str, Any]]:
    """Статус задачи. В sync режиме после run_task_sync не храним; для celery/rq — опрос backend."""
    if task_id in _SYNC_RESULTS:
        return _SYNC_RESULTS[task_id]
    settings = get_settings()
    if (settings.QUEUE_MODE or "").lower() in ("celery", "rq"):
        # placeholder: в проде запрос к redis/celery result backend
        return {"task_id": task_id, "status": "unknown"}
    return None


def register_task(name: str, fn: callable) -> None:
    _TASK_REGISTRY[name] = fn


def get_registry() -> Dict[str, callable]:
    return dict(_TASK_REGISTRY)
