"""
Rate limiting: check_rate_limit, consume_rate_limit, get_rate_limit_headers.
In-memory fallback; future Redis backend.
"""
from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

# Tier: guest, free, plus, pro, admin, export, login
DEFAULT_LIMITS: Dict[str, Tuple[int, int]] = {
    "guest": (30, 60),      # 30 req / 60 sec
    "free": (60, 60),
    "plus": (120, 60),
    "pro": (200, 60),
    "admin": (100, 60),
    "export": (10, 60),
    "login": (5, 300),      # 5 попыток / 5 мин
}

_bucket: Dict[str, list] = {}  # key -> [timestamp, ...]


def _get_limit(tier: str) -> Tuple[int, int]:
    return DEFAULT_LIMITS.get(tier, (60, 60))


def _make_key(key: str, route: str, tier: str) -> str:
    return f"{tier}:{route}:{key}"


def _trim_bucket(key: str, window_sec: int) -> None:
    now = time.time()
    cutoff = now - window_sec
    if key in _bucket:
        _bucket[key] = [t for t in _bucket[key] if t > cutoff]
    else:
        _bucket[key] = []


def check_rate_limit(key: str, route: str = "api", tier: str = "guest") -> Tuple[bool, int, int]:
    """
    Проверяет, не превышен ли лимит. Не потребляет слот.
    Returns: (allowed, remaining, reset_seconds).
    """
    limit, window = _get_limit(tier)
    k = _make_key(key, route, tier)
    _trim_bucket(k, window)
    current = len(_bucket.get(k, []))
    remaining = max(0, limit - current)
    allowed = current < limit
    return allowed, remaining, window


def consume_rate_limit(key: str, route: str = "api", tier: str = "guest") -> Tuple[bool, int, int]:
    """
    Потребляет один слот. Returns: (allowed, remaining, reset_seconds).
    """
    limit, window = _get_limit(tier)
    k = _make_key(key, route, tier)
    _trim_bucket(k, window)
    current = len(_bucket.get(k, []))
    if current >= limit:
        return False, 0, window
    _bucket.setdefault(k, []).append(time.time())
    return True, max(0, limit - len(_bucket[k])), window


def get_rate_limit_headers(key: str, route: str = "api", tier: str = "guest") -> Dict[str, str]:
    """Заголовки X-RateLimit-* для ответа."""
    allowed, remaining, window = check_rate_limit(key, route, tier)
    return {
        "X-RateLimit-Limit": str(_get_limit(tier)[0]),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(int(time.time()) + window),
    }
