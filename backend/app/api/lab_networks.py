"""Публичные эндпоинты статуса лабораторных интеграций и заглушки OAuth/sync."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header

from app.services.lab_network import get_adapter, list_lab_meta
from app.services.user_store import get_or_create_user_id

router = APIRouter(prefix="/api/lab-networks", tags=["lab-networks"])


@router.get("")
def list_labs() -> dict[str, Any]:
    return {"labs": list_lab_meta()}


@router.get("/{lab_id}/status")
def lab_status(lab_id: str) -> dict[str, Any]:
    ad = get_adapter(lab_id)
    if not ad:
        return {"ok": False, "error": "unknown_lab", "id": lab_id}
    return {"ok": True, "id": ad.id, "title": ad.title, **ad.status()}


@router.post("/{lab_id}/authorize")
def lab_authorize(
    lab_id: str,
    body: dict | None = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> dict[str, Any]:
    """Старт OAuth — пока всегда заглушка (контракт для мобильного клиента)."""
    _ = get_or_create_user_id(x_user_id or "")
    ad = get_adapter(lab_id)
    if not ad:
        return {"ok": False, "error": "unknown_lab"}
    redirect_uri = (body or {}).get("redirect_uri") or "https://zazdorovie.ru/app.html"
    return ad.authorize_url(str(redirect_uri))


@router.post("/{lab_id}/sync")
def lab_sync(
    lab_id: str,
    body: dict | None = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> dict[str, Any]:
    """Импорт результатов — заглушка до реальных токенов пользователя."""
    _ = get_or_create_user_id(x_user_id or "")
    ad = get_adapter(lab_id)
    if not ad:
        return {"ok": False, "error": "unknown_lab"}
    return {
        "ok": False,
        "error": "not_configured",
        "message": "Синхронизация будет доступна после подключения API лаборатории и OAuth.",
        "lab": ad.id,
    }
