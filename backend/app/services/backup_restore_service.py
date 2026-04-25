"""
Backup / Restore: контракт и хелперы. Полный автоматический restore не выполнять без guard.
"""
from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.settings import get_settings

logger = logging.getLogger(__name__)
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_DEFAULT_BACKUP_DIR = _BACKEND_DIR / "data" / "backups"


def create_backup_snapshot(
    include_users: bool = True,
    include_audit: bool = True,
    include_quality: bool = True,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Создаёт снимок данных (копии директорий). Возвращает metadata с путём и списком включённых папок.
    """
    backup_dir = Path(get_settings().FILE_STORAGE_PATH) if get_settings().FILE_STORAGE_PATH else _BACKEND_DIR / "data"
    snapshot_dir = _DEFAULT_BACKUP_DIR / f"snapshot_{int(time.time())}_{label or 'manual'}"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    included = []
    data_root = backup_dir if backup_dir.is_dir() else _BACKEND_DIR / "data"
    if include_users and (data_root / "users").exists():
        dest = snapshot_dir / "users"
        shutil.copytree(data_root / "users", dest, dirs_exist_ok=True)
        included.append("users")
    if include_audit and (data_root / "audit").exists():
        dest = snapshot_dir / "audit"
        shutil.copytree(data_root / "audit", dest, dirs_exist_ok=True)
        included.append("audit")
    if include_quality and (data_root / "quality").exists():
        dest = snapshot_dir / "quality"
        shutil.copytree(data_root / "quality", dest, dirs_exist_ok=True)
        included.append("quality")
    return {
        "ok": True,
        "path": str(snapshot_dir),
        "included": included,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def list_backup_snapshots() -> List[Dict[str, Any]]:
    """Список доступных снимков (по директориям в backup folder)."""
    if not _DEFAULT_BACKUP_DIR.exists():
        return []
    result = []
    for d in sorted(_DEFAULT_BACKUP_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if d.is_dir() and d.name.startswith("snapshot_"):
            result.append({"path": str(d), "name": d.name})
    return result


def verify_backup_snapshot(path: str) -> Dict[str, Any]:
    """Проверяет целостность снимка (наличие директорий)."""
    p = Path(path)
    if not p.is_dir():
        return {"ok": False, "error": "Path is not a directory"}
    return {"ok": True, "path": path}


def restore_backup_snapshot(
    path: str,
    *,
    confirm: bool = False,
    target_data_root: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Восстанавливает данные из снимка. Требует confirm=True.
    Опасная операция — не вызывать автоматически без явного подтверждения.
    """
    if not confirm:
        return {"ok": False, "error": "Restore requires confirm=True"}
    p = Path(path)
    if not p.is_dir():
        return {"ok": False, "error": "Snapshot path not found"}
    target = Path(target_data_root) if target_data_root else _BACKEND_DIR / "data"
    try:
        for name in ("users", "audit", "quality"):
            src = p / name
            if src.is_dir():
                dest = target / name
                dest.mkdir(parents=True, exist_ok=True)
                for item in src.iterdir():
                    dest_item = dest / item.name
                    if item.is_dir():
                        shutil.copytree(item, dest_item, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, dest_item)
        return {"ok": True, "path": path, "target": str(target)}
    except Exception as e:
        logger.exception("restore_backup_failed")
        return {"ok": False, "error": str(e)}
