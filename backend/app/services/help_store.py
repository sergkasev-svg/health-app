"""FAQ и пользовательские вопросы в разделе «Помощь». Админ управляет FAQ и отвечает на вопросы."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _BACKEND_DIR / "data"
_FAQ_FILE = _DATA_DIR / "help_faq.json"
_USER_QUESTIONS_FILE = _DATA_DIR / "help_user_questions.json"

FAQ_CATEGORIES = (
    "общее",
    "настройка",
    "показатели",
    "анализы",
    "жалобы",
    "нутрициология",
    "биохимия",
    "микробиом",
    "питание",
    "упражнения",
)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_faq() -> list[dict[str, Any]]:
    """Список FAQ для всех (публичный)."""
    data = _read_json(_FAQ_FILE)
    items = [x for x in (data.get("items") or []) if isinstance(x, dict)]
    items.sort(key=lambda x: (int(x.get("order") or 0), str(x.get("created_at") or "")))
    return items


def get_faq_item(item_id: str) -> dict[str, Any] | None:
    data = _read_json(_FAQ_FILE)
    for it in data.get("items") or []:
        if isinstance(it, dict) and str(it.get("id") or "") == str(item_id or "").strip():
            return it
    return None


def create_faq(question: str, answer: str, category: str = "общее") -> dict[str, Any]:
    data = _read_json(_FAQ_FILE)
    items = list(data.get("items") or [])
    order = max((int(x.get("order") or 0) for x in items), default=0) + 1
    item = {
        "id": str(uuid.uuid4()),
        "question": (question or "").strip()[:2000],
        "answer": (answer or "").strip()[:10000],
        "category": (category or "общее").strip().lower() if (category or "").strip().lower() in FAQ_CATEGORIES else "общее",
        "order": order,
        "created_at": round(time.time(), 2),
        "updated_at": round(time.time(), 2),
    }
    items.append(item)
    data["items"] = items
    _write_json(_FAQ_FILE, data)
    return item


def update_faq(item_id: str, question: str | None = None, answer: str | None = None, category: str | None = None, order: int | None = None) -> dict[str, Any] | None:
    data = _read_json(_FAQ_FILE)
    items = list(data.get("items") or [])
    for i, it in enumerate(items):
        if not isinstance(it, dict) or str(it.get("id") or "") != str(item_id or "").strip():
            continue
        next_it = dict(it)
        if question is not None:
            next_it["question"] = (question or "").strip()[:2000]
        if answer is not None:
            next_it["answer"] = (answer or "").strip()[:10000]
        if category is not None:
            next_it["category"] = (category or "общее").strip().lower() if (category or "").strip().lower() in FAQ_CATEGORIES else it.get("category", "общее")
        if order is not None:
            next_it["order"] = int(order)
        next_it["updated_at"] = round(time.time(), 2)
        items[i] = next_it
        data["items"] = items
        _write_json(_FAQ_FILE, data)
        return next_it
    return None


def delete_faq(item_id: str) -> bool:
    data = _read_json(_FAQ_FILE)
    items = [x for x in (data.get("items") or []) if isinstance(x, dict) and str(x.get("id") or "") != str(item_id or "").strip()]
    if len(items) == len(data.get("items") or []):
        return False
    data["items"] = items
    _write_json(_FAQ_FILE, data)
    return True


def list_user_questions(user_id: str | None, admin: bool = False) -> list[dict[str, Any]]:
    """Вопросы пользователей: если admin — все, иначе только своего user_id."""
    data = _read_json(_USER_QUESTIONS_FILE)
    items = [x for x in (data.get("items") or []) if isinstance(x, dict)]
    if not admin and user_id:
        items = [x for x in items if str(x.get("user_id") or "") == str(user_id)]
    items.sort(key=lambda x: float(x.get("created_at") or 0), reverse=True)
    return items


def create_user_question(user_id: str, question: str) -> dict[str, Any]:
    data = _read_json(_USER_QUESTIONS_FILE)
    items = list(data.get("items") or [])
    item = {
        "id": str(uuid.uuid4()),
        "user_id": (user_id or "").strip() or "anonymous",
        "question": (question or "").strip()[:2000],
        "answer": None,
        "answered_by_type": None,
        "answered_at": None,
        "created_at": round(time.time(), 2),
    }
    items.append(item)
    data["items"] = items[-500:]
    _write_json(_USER_QUESTIONS_FILE, data)
    return item


def answer_user_question(item_id: str, answer: str, answered_by_type: str = "admin") -> dict[str, Any] | None:
    by_type = (answered_by_type or "admin").strip().lower()
    if by_type not in ("admin", "ai", "user"):
        by_type = "admin"
    data = _read_json(_USER_QUESTIONS_FILE)
    items = list(data.get("items") or [])
    for i, it in enumerate(items):
        if not isinstance(it, dict) or str(it.get("id") or "") != str(item_id or "").strip():
            continue
        next_it = dict(it)
        next_it["answer"] = (answer or "").strip()[:10000]
        next_it["answered_by_type"] = by_type
        next_it["answered_at"] = round(time.time(), 2)
        items[i] = next_it
        data["items"] = items
        _write_json(_USER_QUESTIONS_FILE, data)
        return next_it
    return None


def delete_user_question(item_id: str) -> bool:
    data = _read_json(_USER_QUESTIONS_FILE)
    items = [x for x in (data.get("items") or []) if isinstance(x, dict) and str(x.get("id") or "") != str(item_id or "").strip()]
    if len(items) == len(data.get("items") or []):
        return False
    data["items"] = items
    _write_json(_USER_QUESTIONS_FILE, data)
    return True
