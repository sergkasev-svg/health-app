from __future__ import annotations

import re
from typing import Any

BANNED_BY_BRANCH = {
    "oral_cavity": [r"порез", r"жгут", r"валидол", r"прострел в пояснице"],
    "orthopedics": [r"флюс", r"удаление зуба", r"неприятный запах изо рта"],
}


def clean(
    *,
    response_text: str,
    case_state: dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> str:
    """Удаляет из ответа строки, нерелевантные текущей ветке; дедупликация; ограничение длины."""
    text = (response_text or "").strip()
    if not text:
        return ""

    branch = (policy or {}).get("active_branch", "general")
    patterns = BANNED_BY_BRANCH.get(branch, [])

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    kept: list[str] = []
    for line in lines:
        lowered = line.lower()
        if any(re.search(pattern, lowered) for pattern in patterns):
            continue
        kept.append(line)

    result = "\n".join(kept)

    # remove duplicate consecutive lines
    deduped: list[str] = []
    prev = ""
    for line in result.splitlines():
        if line == prev:
            continue
        deduped.append(line)
        prev = line

    result = "\n".join(deduped).strip()

    # Раньше лимит 1200 символов резал длинные шаблонные ответы (астения) до «нервная сист...».
    # Оставляем только защиту от явно раздутого текста.
    _max_chars = 48000
    if len(result) > _max_chars:
        result = result[: _max_chars - 1].rstrip() + "…"

    return result
