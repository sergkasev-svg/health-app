"""
Фильтр гипотез для organic acids report.
Запрещает histamine intolerance, migraine, UTI, lipids и т.п. без прямой симптомной поддержки.
Максимум 5 гипотез, 3 в summary. Убирает дубли и обрывки.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List


FORBIDDEN_WITHOUT_SYMPTOM_SUPPORT = [
    "histamine intolerance",
    "непереносимость гистамина",
    "migraine",
    "мигрен",
    "food allergy",
    "пищевая аллергия",
    "food allergy-like",
    "infection lower uti",
    "цистит",
    "пиелонефрит",
    "инфекция мочевыводящих",
    "липид",
    "холестер",
    "ldl",
    "insomnia",
    "бессонниц",
    "инсомни",
    "anemia",
    "анемия железодефици",
    "железодефицит",
    "cortisol",
    "кортизол",
]

DUPLICATE_PREFIXES = [
    r"^гипотеза:\s*гипотеза:",
    r"^гипотеза:\s*гипотеза\s*:",
]

JUNK_FRAGMENTS = [
    "в т.ч.",
    "подбирать решения с учетом пола",
    "подбирать с учетом даты рождения",
]


def _is_forbidden(text: str) -> bool:
    low = (text or "").lower()
    return any(f in low for f in FORBIDDEN_WITHOUT_SYMPTOM_SUPPORT)


def _has_duplicate_prefix(text: str) -> bool:
    for pat in DUPLICATE_PREFIXES:
        if re.search(pat, text, re.I):
            return True
    return False


def _is_junk_fragment(text: str) -> bool:
    s = (text or "").strip()
    if not s or len(s) < 10:
        return True
    low = s.lower()
    return any(j in low for j in JUNK_FRAGMENTS)


def _dedupe_keep_order(items: List[str]) -> List[str]:
    out: List[str] = []
    seen: set = set()
    for x in items or []:
        s = re.sub(r"\s+", " ", str(x or "").strip())
        if not s:
            continue
        key = s.lower()[:100]
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _fix_duplicate_prefix(text: str) -> str:
    s = str(text or "").strip()
    for pat in DUPLICATE_PREFIXES:
        s = re.sub(pat, "Гипотеза: ", s, flags=re.I)
    return s


def filter_organic_acids_hypotheses(
    hypotheses: List[str],
    max_total: int = 5,
    max_summary: int = 3,
) -> Dict[str, Any]:
    """
    Фильтрует гипотезы для organic acids report.
    Возвращает {filtered: [...], summary: [...], removed: [...]}.
    """
    removed: List[str] = []
    filtered: List[str] = []

    for h in hypotheses or []:
        s = str(h or "").strip()
        if not s:
            continue
        if _is_forbidden(s):
            removed.append(s)
            continue
        if _has_duplicate_prefix(s):
            s = _fix_duplicate_prefix(s)
        if _is_junk_fragment(s):
            removed.append(s)
            continue
        filtered.append(s)

    filtered = _dedupe_keep_order(filtered)[:max_total]
    summary = filtered[:max_summary]

    return {
        "filtered": filtered,
        "summary": summary,
        "removed": removed,
    }
