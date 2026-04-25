"""Upload API: загрузка файлов анализов (PDF, изображения). Извлечение текста для отчёта."""
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

from fastapi import APIRouter, File, Header, UploadFile

from app.services.document_extraction import extract_text_from_file
from app.services.lab_upload_signals import maybe_notify_after_lab_upload
from app.services.user_store import add_document, get_or_create_user_id, normalize_subject_id

router = APIRouter(prefix="/api", tags=["upload"])

# Каталог загрузок: backend/data/users/{user_id}/uploads/
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_DATA_ROOT = _BACKEND_DIR / "data" / "users"
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".webp", ".txt"}
MAX_FILE_MB = 50


def _basename_upload_filename(raw: Optional[str]) -> str:
    """Имя файла из multipart: убрать кавычки, путь Chrome (C:/fakepath/), нормализовать Unicode."""
    if not raw:
        return ""
    name = raw.strip().strip('"').strip("'")
    name = name.replace("\\", "/").rstrip("/")
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    if "%" in name:
        try:
            name = unquote(name, encoding="utf-8", errors="replace")
        except Exception:
            pass
    try:
        name = unicodedata.normalize("NFC", name)
    except Exception:
        pass
    return name


def _guess_ext_from_magic(content: bytes) -> Optional[str]:
    """Если расширение в имени потеряно/искажено, определить тип по сигнатуре."""
    if not content or len(content) < 12:
        return None
    if content.startswith(b"%PDF"):
        return ".pdf"
    if content[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WEBP":
        return ".webp"
    # HEIC/HEIF: ... ftyp heic / mif1 ...
    if content[4:8] == b"ftyp" and (b"heic" in content[8:32] or b"mif1" in content[8:32] or b"msf1" in content[8:32]):
        return ".heic"
    if content.startswith((b"II*\x00", b"MM\x00*")):
        return ".tif"
    return None


def _user_uploads_dir(user_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in user_id.strip())[:64] or "default"
    d = _DATA_ROOT / safe / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_upload_file_path(user_id: str, doc: dict) -> Path | None:
    """Путь к файлу документа на диске (для повторного извлечения текста)."""
    if not doc or not doc.get("id") or not doc.get("filename"):
        return None
    ext = Path(doc["filename"]).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None
    d = _user_uploads_dir(user_id)
    path = d / (doc["id"] + ext)
    return path if path.exists() else None


@router.get("/upload/status")
def upload_status():
    return {"status": "ok", "message": "Загрузка анализов доступна."}


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Принять файл анализа (PDF или изображение), сохранить и добавить в документы пользователя."""
    uid = get_or_create_user_id(x_user_id or "")
    sid = normalize_subject_id(x_subject_id or "")
    if not file.filename or not str(file.filename).strip():
        return {"ok": False, "error": "Нет имени файла"}
    content = await file.read()
    if len(content) > MAX_FILE_MB * 1024 * 1024:
        return {"ok": False, "error": f"Размер файла не более {MAX_FILE_MB} МБ"}
    display_name = _basename_upload_filename(file.filename)
    ext = Path(display_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        magic_ext = _guess_ext_from_magic(content)
        if magic_ext in ALLOWED_EXTENSIONS:
            ext = magic_ext
            stem = Path(display_name).stem if display_name else ""
            display_name = f"{stem}{ext}" if stem else f"document{ext}"
        else:
            return {"ok": False, "error": f"Разрешены только: {', '.join(sorted(ALLOWED_EXTENSIONS))}"}
    uploads_dir = _user_uploads_dir(uid)
    doc_id = str(uuid.uuid4())
    save_name = doc_id + ext
    save_path = uploads_dir / save_name
    save_path.write_bytes(content)
    extracted_text = extract_text_from_file(save_path, ext)
    summary = f"Загружен: {display_name}"
    if extracted_text and len(extracted_text.strip()) > 10:
        summary = summary + ". Текст извлечён для анализа."
    add_document(uid, {
        "id": doc_id,
        "type": "report",
        "summary": summary,
        "created_at": time.time(),
        "filename": display_name,
        "extracted_text": extracted_text[:50000] if extracted_text else "",
        "subject_id": sid,
    })
    proactive = maybe_notify_after_lab_upload(
        uid, doc_id, display_name, extracted_text[:50000] if extracted_text else ""
    )
    out: dict = {"ok": True, "id": doc_id, "filename": display_name, "extracted": bool(extracted_text and extracted_text.strip())}
    if proactive:
        out["proactive_notification"] = proactive
    return out
