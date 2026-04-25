from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header
from pydantic import BaseModel

from app.services.mikhail_worker import MikhailWorker
from app.services.user_store import get_or_create_user_id

router = APIRouter(prefix="/api/mikhail", tags=["mikhail"])
_worker = MikhailWorker()


class MikhailChatRequest(BaseModel):
    message: str
    subject_id: Optional[str] = None
    app_mode: Optional[str] = None


@router.post("/chat")
async def mikhail_chat(payload: MikhailChatRequest, x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    user_id = get_or_create_user_id(x_user_id or "")
    result = await _worker.chat(
        user_id=user_id,
        message=payload.message,
        subject_id=payload.subject_id,
        app_mode=payload.app_mode,
    )
    return result


@router.get("/tools")
def mikhail_tools():
    return {"tools": _worker.tool_catalog()}


@router.get("/status")
def mikhail_status(x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    user_id = get_or_create_user_id(x_user_id or "")
    return _worker.status(user_id=user_id)
