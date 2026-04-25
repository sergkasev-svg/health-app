"""
Опциональная доставка push / внешних уведомлений параллельно in-app.

Если задан INTERNAL_PUSH_WEBHOOK_URL — POST JSON на ваш бэкенд (n8n, Firebase Cloud Function и т.д.).
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


def send_internal_push_webhook(
    *,
    user_id: str,
    title: str,
    body: str,
    action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = os.environ.get("INTERNAL_PUSH_WEBHOOK_URL", "").strip()
    if not url:
        return {"sent": False, "reason": "no_webhook_configured"}
    secret = os.environ.get("INTERNAL_PUSH_WEBHOOK_SECRET", "").strip()
    payload = {
        "user_id": str(user_id or "")[:128],
        "title": str(title or "")[:200],
        "body": str(body or "")[:2000],
        "action": action if isinstance(action, dict) else {},
        "source": "knowledge_enrichment",
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if secret:
        headers["X-Webhook-Secret"] = secret
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            _ = resp.read()
        return {"sent": True}
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        logger.info("internal_push_webhook_failed", extra={"error": str(e)[:200]})
        return {"sent": False, "reason": str(e)[:120]}
