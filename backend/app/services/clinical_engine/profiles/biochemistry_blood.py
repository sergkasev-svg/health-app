"""
Профиль biochemistry_blood: при наличии липидных маркеров делегирует в lipid_panel.
Используется из pipeline при document_type = biochemistry_blood.
"""
from __future__ import annotations

from typing import List

from app.services.clinical_engine.contracts import Finding, LabValue
from app.services.clinical_engine.profiles.lipid_panel import interpret_lipids

LIPID_CODES = {"total_cholesterol", "ldl_cholesterol", "hdl_cholesterol", "triglycerides"}


def interpret_biochemistry_blood(values: List[LabValue]) -> List[Finding]:
    """Если есть липидные маркеры — те же правила, что lipid_panel; иначе пусто (для расширения)."""
    codes = {v.code for v in values}
    if codes & LIPID_CODES:
        return interpret_lipids(values)
    return []
