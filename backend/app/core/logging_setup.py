"""
Structured logging: request_id, user_id (sanitized), route, timing.
JSON в prod, читаемый в dev; PII sanitization.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any, Dict, Optional

from app.core.settings import get_settings


def sanitize_for_log(value: Optional[str], max_len: int = 8) -> str:
    """Скрывает PII: оставляет только префикс/длину для отладки."""
    if value is None or not isinstance(value, str):
        return ""
    s = value.strip()
    if not s:
        return ""
    if len(s) <= max_len:
        return s[:2] + "***" if len(s) > 2 else "***"
    return s[:2] + "***" + str(len(s))


def redact_dict(d: Dict[str, Any], keys_redact: Optional[set] = None) -> Dict[str, Any]:
    keys_redact = keys_redact or {"password", "token", "secret", "authorization", "cookie"}
    out = {}
    for k, v in d.items():
        k_lower = k.lower()
        if any(r in k_lower for r in keys_redact):
            out[k] = "[REDACTED]"
        elif isinstance(v, dict):
            out[k] = redact_dict(v, keys_redact)
        else:
            out[k] = v
    return out


class StructuredFormatter(logging.Formatter):
    """JSON в prod, обычный текст в dev."""

    def __init__(self, use_json: bool = False) -> None:
        self.use_json = use_json
        super().__init__()

    def format(self, record: logging.LogRecord) -> str:
        extra: Dict[str, Any] = {
            "message": record.getMessage(),
            "level": record.levelname,
            "logger": record.name,
            "timestamp": self.formatTime(record, self.datefmt),
        }
        if hasattr(record, "request_id"):
            extra["request_id"] = getattr(record, "request_id", "")
        if hasattr(record, "user_id"):
            extra["user_id"] = sanitize_for_log(getattr(record, "user_id", ""))
        if hasattr(record, "route"):
            extra["route"] = getattr(record, "route", "")
        if hasattr(record, "state"):
            extra["state"] = getattr(record, "state", "")
        if hasattr(record, "urgency"):
            extra["urgency"] = getattr(record, "urgency", "")
        if record.exc_info:
            extra["error"] = self.formatException(record.exc_info)
        for k, v in record.__dict__.items():
            if k not in ("message", "msg", "args", "created", "filename", "funcName", "levelname", "levelno",
                        "lineno", "module", "msecs", "pathname", "process", "processName", "relativeCreated",
                        "stack_info", "exc_info", "exc_text", "thread", "threadName", "name", "msg", "args",
                        "request_id", "user_id", "route", "state", "urgency"):
                extra[k] = v
        extra = redact_dict(extra)
        if self.use_json:
            return json.dumps(extra, ensure_ascii=False)
        parts = [f"[{extra.get('level', 'INFO')}]", extra.get("message", "")]
        if extra.get("request_id"):
            parts.append(f"req={extra['request_id'][:8]}")
        if extra.get("route"):
            parts.append(extra["route"])
        return " ".join(str(p) for p in parts)


def setup_logging() -> None:
    """Инициализация логгера: уровень и формат из настроек."""
    settings = get_settings()
    level = getattr(logging, (settings.LOG_LEVEL or "INFO").upper(), logging.INFO)
    use_json = settings.APP_ENV == "prod"
    fmt = StructuredFormatter(use_json=use_json)
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(fmt)
        root.addHandler(h)
