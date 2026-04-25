# -*- coding: utf-8 -*-
"""
Эвристики по тексту загруженного анализа: возможные отклонения для проактивного уведомления.
Не клинический вердикт — только триггер для UX (уведомление → раздел «Анализы» / консьерж).
"""
from __future__ import annotations

import re
from typing import Any


_RE_STRONG_NORMAL = re.compile(
    r"(все\s+показатели\s+в\s+норме|без\s+отклонени| в\s+пределах\s+референс|референсных\s+значени)",
    re.IGNORECASE | re.UNICODE,
)

_RE_DEVIATION = re.compile(
    r"(повышен|понижен|повышени|понижени|отклонени|выше\s+норм|ниже\s+норм|патолог"
    r"|патологическ|критическ|\+\+\+|\+\+|↑|↓|угроз|значимо\s+измен)",
    re.IGNORECASE | re.UNICODE,
)


def extract_deviation_hint(text: str | None) -> dict[str, Any]:
    """Возвращает флаги и короткую подсказку для уведомления."""
    raw = (text or "").strip()
    if len(raw) < 12:
        return {"likely_deviation": False, "hint": "", "confidence": "none"}

    sample = raw[:12000]
    if _RE_STRONG_NORMAL.search(sample) and not _RE_DEVIATION.search(sample):
        return {"likely_deviation": False, "hint": "", "confidence": "low"}

    if _RE_DEVIATION.search(sample):
        return {
            "likely_deviation": True,
            "hint": "В тексте результата встречаются формулировки об отклонениях или крайних значениях.",
            "confidence": "heuristic",
        }
    return {"likely_deviation": False, "hint": "", "confidence": "low"}


def maybe_notify_after_lab_upload(
    user_id: str,
    document_id: str,
    filename: str,
    extracted_text: str | None,
) -> dict[str, Any] | None:
    """Создаёт in-app уведомление при эвристическом обнаружении отклонений."""
    hint = extract_deviation_hint(extracted_text)
    if not hint.get("likely_deviation"):
        return None

    from app.services.user_store import add_notification

    title = "Анализ: проверьте отклонения"
    body = (
        f"Файл «{filename or 'анализ'}»: по тексту похоже на отклонения от нормы. "
        "Откройте раздел «Анализы» или спросите Михаила, что это может значить для вас."
    )
    action = {"type": "open_app_path", "hash": "labs", "document_id": document_id}
    add_notification(user_id, title, body, unread=True, action=action)
    return {"notified": True, "document_id": document_id, "hint": hint}
