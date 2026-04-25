"""
Точка входа FastAPI: CORS, маршруты API, статика фронтенда.
Production hardening: logging, settings, startup checks, health, error handlers.
"""
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from fastapi import Body, FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import PlainTextResponse

_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from app.api import user, upload, knowledge, admin_quality, health, ai, payments, memory, api_reports, mikhail, lab_networks
from app.database import ensure_database_schema
from app.core.logging_setup import setup_logging
from app.core.settings import get_settings
from app.core.startup_checks import run_startup_checks
from app.core.error_handlers import register_error_handlers
from app.services.user_store import (
    clear_symptom_entries as store_clear_symptom_entries,
    delete_symptom_entries as store_delete_symptom_entries,
    get_or_create_user_id,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    get_settings()
    try:
        ensure_database_schema()
    except Exception as e:
        logging.getLogger(__name__).warning("ensure_database_schema_failed: %s", e)
    ok, warnings = run_startup_checks()
    for w in warnings:
        logging.getLogger(__name__).warning("startup_warning: %s", w)
    try:
        from app.services.background_tasks_registry import register_background_tasks
        register_background_tasks()
    except Exception as e:
        logging.getLogger(__name__).warning("background_tasks_registry_failed: %s", e)
    yield
    # graceful shutdown: optional cleanup


app = FastAPI(title="Health App API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

# Маркетинговые HTML после деплоя не должны долго залипать в браузере/CDN.
_HTML_NO_STALE_CACHE = {"Cache-Control": "public, max-age=0, must-revalidate"}


@app.get("/health")
def health_legacy():
    return {"status": "ok"}


@app.get("/")
def serve_root_index():
    """Стартовая страница как на проде: отдаём index.html (без редиректа на /app.html#dashboard)."""
    path = _frontend_public / "index.html"
    if not path.exists():
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(path, media_type="text/html", headers=_HTML_NO_STALE_CACHE)


@app.get("/api/version")
def version():
    return {"version": "0.1.0"}


@app.get("/api/debug/symptoms-delete")
def debug_symptoms_delete():
    """Проверка, что на порту отвечает наш бэкенд. Если этот GET возвращает 200 — POST /api/user/symptoms/delete тоже должен работать."""
    return {"supported": True, "method": "POST", "path": "/api/user/symptoms/delete"}


@app.get("/api/debug/dispatch")
def debug_dispatch():
    """Есть только при запуске с диспетчером (новая версия). Если 404 — перезапустите сервер полностью."""
    return {"dispatch": True}


def _main_user_id(x: Optional[str] = Header(None, alias="X-User-Id")) -> str:
    return get_or_create_user_id(x or "")


def _do_delete_symptoms_main(uid: str, clear_all: bool, entry_indices: Optional[List[Any]]):
    if clear_all:
        store_clear_symptom_entries(uid)
        return {"user_id": uid, "entries": []}
    indices = []
    for x in entry_indices or []:
        try:
            indices.append(int(x) if isinstance(x, int) else int(float(x)))
        except (TypeError, ValueError):
            pass
    if not indices:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Укажите entry_indices или clear_all: true")
    entries = store_delete_symptom_entries(uid, indices)
    return {"user_id": uid, "entries": entries}


@app.post("/api/user/symptoms/delete")
def api_user_symptoms_delete(
    body: dict = Body(default={}),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Удаление записей симптомов — зарегистрировано в main до статики."""
    uid = _main_user_id(x_user_id)
    clear_all = body.get("clear_all") is True
    entry_indices = body.get("entry_indices")
    return _do_delete_symptoms_main(uid, clear_all, entry_indices)


app.include_router(health.router)
app.include_router(upload.router)
app.include_router(user.router)
app.include_router(knowledge.router)
app.include_router(admin_quality.router)
app.include_router(ai.router)
app.include_router(memory.router)
app.include_router(payments.router)
app.include_router(api_reports.router)
app.include_router(mikhail.router)
app.include_router(lab_networks.router)

# Диспетчер: /api и /health — в FastAPI, остальное — статика (избегаем 405 на POST /api/* из-за Mount("/"))
_fastapi_app = app
_frontend_public = _backend_dir.parent / "frontend" / "public"
_static_app = StaticFiles(directory=str(_frontend_public), html=True) if _frontend_public.exists() else None

if not _frontend_public.exists():
    logging.getLogger(__name__).warning("frontend_public not found at %s — /app.html and static assets may 404", _frontend_public)


@app.get("/app.html")
def serve_app_html():
    """Явная отдача app.html, чтобы дашборд открывался по http://127.0.0.1:8000/app.html#dashboard даже при сбое статики."""
    path = _frontend_public / "app.html"
    if not path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="app.html not found")
    return FileResponse(path, media_type="text/html", headers=_HTML_NO_STALE_CACHE)


@app.get("/landing.html")
def serve_landing_html():
    path = _frontend_public / "landing.html"
    if not path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="landing.html not found")
    return FileResponse(path, media_type="text/html", headers=_HTML_NO_STALE_CACHE)


@app.get("/presentation/")
def serve_presentation_index():
    path = _frontend_public / "presentation" / "index.html"
    if not path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="presentation not found")
    return FileResponse(path, media_type="text/html", headers=_HTML_NO_STALE_CACHE)


@app.get("/presentation")
def serve_presentation_no_trailing_slash():
    return RedirectResponse(url="/presentation/", status_code=307)


@app.get("/microbiome-landing.html")
def microbiome_landing_retired():
    """Старый лендинг снят — ведём на основной лендинг."""
    return RedirectResponse(url="/landing.html", status_code=301)


@app.get("/favicon.ico")
def favicon_ico():
    """Убираем 404 в консоли, если иконка браузером запрошена по умолчанию."""
    return PlainTextResponse("", status_code=204)


def _to_fastapi(path: str) -> bool:
    return (
        path.startswith("/api")
        or path.startswith("/health")
        or path in ("/", "/app.html", "/landing.html", "/presentation", "/presentation/", "/microbiome-landing.html", "/favicon.ico")
        or path in ("/docs", "/redoc", "/openapi.json")
    )


def _starlette_http_as_text(exc: StarletteHTTPException) -> str:
    d = exc.detail
    if isinstance(d, str):
        return d
    return "Not Found"


async def _route_dispatch(scope, receive, send):
    path = (scope.get("path") or "").split("?")[0]
    if _to_fastapi(path):
        await _fastapi_app(scope, receive, send)
    elif _static_app is not None:
        try:
            await _static_app(scope, receive, send)
        except StarletteHTTPException as exc:
            # Иначе Starlette отдаёт необработанное исключение → 500 у клиента (nginx «Internal error»).
            resp = PlainTextResponse(_starlette_http_as_text(exc), status_code=exc.status_code)
            await resp(scope, receive, send)
    else:
        await _fastapi_app(scope, receive, send)


def _security_response_headers() -> List[Tuple[bytes, bytes]]:
    """Заголовки для Lighthouse / OWASP: COOP, XFO, CSP (без inline-скриптов в HTML), HSTS только в production."""
    settings = get_settings()
    csp = (
        "default-src 'self'; "
        "base-uri 'self'; "
        "frame-ancestors 'self'; "
        "form-action 'self'; "
        "img-src 'self' data: https: blob:; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "connect-src 'self' https: wss: data: blob:; "
        "media-src 'self' blob: data:; "
        "worker-src 'self'; "
    )
    out: List[Tuple[bytes, bytes]] = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"SAMEORIGIN"),
        (b"referrer-policy", b"strict-origin-when-cross-origin"),
        (
            b"permissions-policy",
            b"accelerometer=(), camera=(self), display-capture=(self), geolocation=(), "
            b"microphone=(self), payment=(), usb=()",
        ),
        (b"cross-origin-opener-policy", b"same-origin"),
        (b"content-security-policy", csp.encode("utf-8")),
    ]
    if (settings.APP_ENV or "").lower() in ("production", "prod"):
        out.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains; preload"))
    return out


async def _dispatch(scope: dict, receive: Callable, send: Callable) -> None:
    if scope.get("type") != "http":
        await _route_dispatch(scope, receive, send)
        return

    sec = _security_response_headers()

    async def send_wrapper(message: dict) -> None:
        if message.get("type") == "http.response.start":
            raw = message.get("headers") or []
            merged: List[Tuple[bytes, bytes]] = list(raw) + sec
            message["headers"] = merged
        await send(message)

    await _route_dispatch(scope, receive, send_wrapper)


# Для uvicorn экспортируем диспетчер, чтобы POST /api/* не перехватывала статика
app = _dispatch
