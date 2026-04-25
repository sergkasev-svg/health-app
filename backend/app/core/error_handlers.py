"""
Глобальные обработчики исключений: безопасные ответы API, без утечки stack trace в prod.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.core.settings import get_settings

logger = logging.getLogger(__name__)


def _is_debug() -> bool:
    try:
        return get_settings().DEBUG
    except Exception:
        return False


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "message": "Validation error"},
    )


async def pydantic_validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "message": "Validation error"},
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if hasattr(exc, "status_code") and hasattr(exc, "detail"):
        return JSONResponse(status_code=getattr(exc, "status_code", 500), content={"detail": str(getattr(exc, "detail", str(exc)))})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_exception", extra={"path": request.url.path})
    detail: Any = "Internal server error"
    if _is_debug():
        detail = str(exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": detail},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ValidationError, pydantic_validation_handler)
    from fastapi import HTTPException
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
