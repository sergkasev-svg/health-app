"""
Проверки загружаемых файлов: размер, тип, безопасное имя.
Whitelist типов; не доверять имени файла как источнику правды.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

# Разрешённые расширения для медицинских документов
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".png", ".jpg", ".jpeg", ".heic", ".webp"}
# Опасные расширения — всегда отклонять
DANGEROUS_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".ps1", ".vbs", ".js", ".jar", ".py", ".php",
    ".asp", ".aspx", ".jsp", ".htaccess", ".scr", ".pif", ".com",
}
MAX_FILE_SIZE_MB = 15
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


def sanitize_filename(filename: str, max_length: int = 200) -> str:
    """Безопасно нормализует имя файла: убирает путь, нежелательные символы."""
    if not filename or not isinstance(filename, str):
        return "unnamed"
    # убрать путь
    name = Path(filename).name
    # оставить буквы, цифры, точку, дефис, подчёркивание
    name = re.sub(r"[^\w.\-]", "_", name, flags=re.UNICODE)
    name = re.sub(r"_+", "_", name).strip("._")
    return name[:max_length] if name else "unnamed"


def detect_supported_medical_doc_type(filename: str, content_type: Optional[str] = None) -> Optional[str]:
    """
    Определяет допустимый тип документа по имени и опционально content_type.
    Возвращает расширение (например .pdf) или None если не поддерживается.
    """
    name = (filename or "").strip().lower()
    ext = Path(name).suffix.lower() if name else ""
    if ext in DANGEROUS_EXTENSIONS:
        return None
    if ext in ALLOWED_EXTENSIONS:
        return ext
    # по content_type
    if content_type:
        c = content_type.split(";")[0].strip().lower()
        if "pdf" in c:
            return ".pdf"
        if "image/jpeg" in c or "image/jpg" in c:
            return ".jpg"
        if "image/png" in c:
            return ".png"
        if "image/heic" in c:
            return ".heic"
        if "image/webp" in c:
            return ".webp"
        if "text/plain" in c:
            return ".txt"
    return None


def reject_oversized_or_unsafe_file(
    size_bytes: int,
    filename: str,
    content_type: Optional[str] = None,
) -> Optional[str]:
    """
    Проверяет размер и тип. Возвращает None если ок, иначе строку ошибки.
    """
    if size_bytes > MAX_FILE_SIZE_BYTES:
        return f"Файл слишком большой (макс. {MAX_FILE_SIZE_MB} МБ)"
    ext = Path((filename or "").strip()).suffix.lower()
    if ext in DANGEROUS_EXTENSIONS:
        return "Тип файла не разрешён"
    detected = detect_supported_medical_doc_type(filename, content_type)
    if not detected:
        return f"Разрешены только: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
    return None


def validate_uploaded_file(
    filename: Optional[str],
    size_bytes: int,
    content_type: Optional[str] = None,
) -> Tuple[bool, str, Optional[str]]:
    """
    Валидация загруженного файла.
    Returns: (ok, sanitized_filename, error_message).
    """
    safe_name = sanitize_filename(filename or "unnamed")
    err = reject_oversized_or_unsafe_file(size_bytes, filename or "", content_type)
    if err:
        return False, safe_name, err
    return True, safe_name, None
