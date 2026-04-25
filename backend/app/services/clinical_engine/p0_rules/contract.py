"""
Единый контракт результатов правил P0 (совместим с report builder / UI).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MarkerSnapshot:
    """Нормализованное значение маркера для rule engine."""

    value: Optional[float] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    value_text: Optional[str] = None
    status: Optional[str] = None


@dataclass
class RuleResult:
    """Результат применения профиля правил."""

    findings: List[Dict[str, Any]] = field(default_factory=list)
    hypotheses: List[Dict[str, Any]] = field(default_factory=list)
    next_steps: List[Dict[str, Any]] = field(default_factory=list)
    risk: Optional[Dict[str, Any]] = None
