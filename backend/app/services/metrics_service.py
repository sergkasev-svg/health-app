"""
Метрики: increment_counter, record_timing, set_gauge, track_export_job и др.
No-op при отключённых метриках; fallback-safe.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from app.core.settings import get_settings

logger = logging.getLogger(__name__)
_gauges: Dict[str, float] = {}
_counters: Dict[str, int] = {}


def _metrics_enabled() -> bool:
    try:
        return get_settings().METRICS_ENABLED
    except Exception:
        return False


def increment_counter(name: str, value: int = 1, tags: Optional[Dict[str, str]] = None) -> None:
    if not _metrics_enabled():
        return
    key = name + (f":{tags}" if tags else "")
    _counters[key] = _counters.get(key, 0) + value


def record_timing(name: str, duration_sec: float, tags: Optional[Dict[str, str]] = None) -> None:
    if not _metrics_enabled():
        return
    logger.debug("timing", extra={"name": name, "duration_sec": duration_sec, "tags": tags or {}})


def set_gauge(name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
    if not _metrics_enabled():
        return
    key = name + (f":{tags}" if tags else "")
    _gauges[key] = value


def track_state_distribution(state: str, count: int = 1) -> None:
    increment_counter("clinical.state", value=count, tags={"state": state})


def track_export_job(job_type: str, status: str) -> None:
    increment_counter("export.job", tags={"type": job_type, "status": status})


def track_parsing_failure(reason: str) -> None:
    increment_counter("parsing.failure", tags={"reason": reason})


def track_hallucination_failure() -> None:
    increment_counter("hallucination.failure")


def track_gating_event(event: str) -> None:
    increment_counter("gating.event", tags={"event": event})


def track_onboarding_first_value() -> None:
    increment_counter("onboarding.first_value")


def track_upgrade_prompt_shown() -> None:
    increment_counter("product.upgrade_prompt_shown")


def get_gauges() -> Dict[str, float]:
    return dict(_gauges)


def get_counters() -> Dict[str, int]:
    return dict(_counters)
