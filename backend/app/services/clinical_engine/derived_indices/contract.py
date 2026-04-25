"""
Единый контракт расчётных интегральных индексов (не заменяют клиническую интерпретацию профиля).
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

ConfidenceLevel = Literal["established", "supportive", "exploratory"]


class DerivedIndex(BaseModel):
    code: str
    title: str
    value: Optional[float] = None
    unit: Optional[str] = None
    status: Optional[str] = None  # краткий класс: «норма», «низкий диапазон», и т.д.
    interpretation: Optional[str] = None
    required_markers: List[str] = Field(default_factory=list)
    missing_markers: List[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = "supportive"
    patient_visible: bool = False
    physician_visible: bool = True
    not_calculated_reason: Optional[str] = None  # если value is None и нужно явное пояснение

    def to_report_line(self) -> str:
        if self.not_calculated_reason or self.value is None:
            miss = ", ".join(self.missing_markers) if self.missing_markers else ""
            base = f"{self.title}: не рассчитан"
            if miss:
                base += f" (отсутствуют: {miss})"
            if self.interpretation:
                base += f". {self.interpretation}"
            return base
        v = self.value
        assert v is not None
        u = f" {self.unit}" if self.unit else ""
        st = f" — {self.status}" if self.status else ""
        interp = f". {self.interpretation}" if self.interpretation else ""
        # компактное форматирование без артефактов .0000
        if v == int(v):
            vs = str(int(v))
        else:
            vs = f"{v:.4g}"
        return f"{self.title}: {vs}{u}{st}{interp}"
