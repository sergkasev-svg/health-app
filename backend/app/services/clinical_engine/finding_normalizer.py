"""
Нормализация findings: дедупликация по code, сортировка по severity.
Вся клиническая логика до этого шага; нормализатор только упорядочивает.
"""
from __future__ import annotations

from typing import List

from app.services.clinical_engine.contracts import Finding

_SEVERITY_ORDER = ("urgent", "high", "moderate", "mild", "borderline", "info")


def _severity_rank(s: str) -> int:
    try:
        return _SEVERITY_ORDER.index(s.lower())
    except ValueError:
        return len(_SEVERITY_ORDER)


def normalize_findings(findings: List[Finding]) -> List[Finding]:
    """
    Дедупликация по code (оставляем первое вхождение), сортировка по убыванию значимости.
    """
    if not findings:
        return []
    seen: set[str] = set()
    deduped: List[Finding] = []
    for f in findings:
        if f.code in seen:
            continue
        seen.add(f.code)
        deduped.append(f)
    return sorted(deduped, key=lambda x: _severity_rank(x.severity))
