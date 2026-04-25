"""
Модели аудита: AuditEvent.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class AuditEvent(BaseModel):
    event_id: str = ""
    timestamp: str = ""
    actor_user_id: Optional[str] = None
    actor_role: Optional[str] = None
    action: str = ""
    target_type: str = ""
    target_id: Optional[str] = None
    status: str = "ok"  # ok | failure | denied
    metadata: Dict[str, Any] = Field(default_factory=dict)
