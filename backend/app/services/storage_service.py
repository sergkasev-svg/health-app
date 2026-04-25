"""
Абстракция хранилища файлов: private/public, local filesystem, future S3-like.
Медицинские документы — private by default; signed/public только где нужно.
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import BinaryIO, Optional, Tuple

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


class StorageService:
    """Единый сервис хранения файлов: local или s3_like (интерфейс)."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._base = self._resolve_base_path()
        self._private_root = self._resolve_private_path()
        self._public_root = self._resolve_public_path()

    def _resolve_base_path(self) -> Path:
        if self._settings.FILE_STORAGE_PATH:
            return Path(self._settings.FILE_STORAGE_PATH)
        return _BACKEND_DIR / "data"

    def _resolve_private_path(self) -> Path:
        if self._settings.PRIVATE_MEDIA_PATH:
            return Path(self._settings.PRIVATE_MEDIA_PATH)
        return self._base / "private"

    def _resolve_public_path(self) -> Path:
        if self._settings.PUBLIC_MEDIA_PATH:
            return Path(self._settings.PUBLIC_MEDIA_PATH)
        return self._base / "public"

    def _ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def save_private_file(
        self,
        content: bytes,
        *,
        relative_path: Optional[str] = None,
        prefix: str = "uploads",
        extension: str = "",
    ) -> str:
        """Сохраняет файл в private storage. Возвращает относительный ключ (path key)."""
        if get_settings().FILE_STORAGE_MODE == "disabled":
            raise RuntimeError("Storage is disabled")
        self._ensure_dir(self._private_root)
        if relative_path:
            key = relative_path.lstrip("/")
        else:
            key = f"{prefix}/{uuid.uuid4().hex}{extension}"
        full = self._private_root / key
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(content)
        return key

    def save_public_file(
        self,
        content: bytes,
        *,
        relative_path: Optional[str] = None,
        prefix: str = "public",
        extension: str = "",
    ) -> str:
        """Сохраняет файл в public storage. Возвращает относительный ключ."""
        if get_settings().FILE_STORAGE_MODE == "disabled":
            raise RuntimeError("Storage is disabled")
        self._ensure_dir(self._public_root)
        if relative_path:
            key = relative_path.lstrip("/")
        else:
            key = f"{prefix}/{uuid.uuid4().hex}{extension}"
        full = self._public_root / key
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(content)
        return key

    def read_private_file(self, key: str) -> Optional[bytes]:
        """Читает файл из private storage по ключу. Не светит сырые пути наружу."""
        full = self._private_root / key.lstrip("/")
        if not full.is_file():
            return None
        try:
            return full.read_bytes()
        except Exception as e:
            logger.warning("read_private_file_failed", extra={"key": key, "error": str(e)})
            return None

    def delete_private_file(self, key: str) -> bool:
        """Удаляет файл из private storage."""
        full = self._private_root / key.lstrip("/")
        if not full.is_file():
            return False
        try:
            full.unlink()
            return True
        except Exception as e:
            logger.warning("delete_private_file_failed", extra={"key": key, "error": str(e)})
            return False

    def generate_signed_url(
        self,
        key: str,
        private: bool = True,
        expires_in_seconds: int = 3600,
    ) -> Optional[str]:
        """
        Генерирует подписанный URL для скачивания.
        Local mode: возвращает путь вида /api/storage/signed?key=... (обрабатывается API).
        S3-like: здесь можно подставить presigned URL.
        """
        if private:
            # В local режиме не отдаём сырой путь; API endpoint отдаёт файл по key с проверкой доступа
            return f"/api/storage/signed?key={key}&expires={expires_in_seconds}"
        return f"/api/storage/public?key={key}"

    def get_private_full_path(self, key: str) -> Optional[Path]:
        """Внутренний метод: полный путь к private файлу (для отдачи через endpoint)."""
        full = self._private_root / key.lstrip("/")
        return full if full.is_file() else None


def get_storage_service() -> StorageService:
    return StorageService()
