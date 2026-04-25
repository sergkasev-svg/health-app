"""
Аудит действий: log_audit_event, build_audit_event. No-crash fallback.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from app.services.audit_models import AuditEvent

logger = logging.getLogger(__name__)
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_AUDIT_LOG_PATH = _BACKEND_DIR / "data" / "audit" / "audit.jsonl"


def build_audit_event(
    action: str,
    target_type: str = "",
    target_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    actor_role: Optional[str] = None,
    status: str = "ok",
    metadata: Optional[Dict[str, Any]] = None,
) -> AuditEvent:
    return AuditEvent(
        event_id=str(uuid.uuid4()),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=action,
        target_type=target_type,
        target_id=target_id,
        status=status,
        metadata=metadata or {},
    )


def log_audit_event(
    action: str,
    target_type: str = "",
    target_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    actor_role: Optional[str] = None,
    status: str = "ok",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Пишет событие в audit log. Не бросает исключений."""
    try:
        event = build_audit_event(
            action=action,
            target_type=target_type,
            target_id=target_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            status=status,
            metadata=metadata or {},
        )
        _AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")
    except Exception as e:
        logger.warning("audit_log_failed", extra={"action": action, "error": str(e)})
