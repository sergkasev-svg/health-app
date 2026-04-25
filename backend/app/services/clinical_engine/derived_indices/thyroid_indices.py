"""Интегральный тиреоидный индекс ИТИ = (fT3 + fT4) / TSH — при единых единицах нужна осторожность."""
from __future__ import annotations

import re
from typing import List, Optional

from app.services.clinical_engine.derived_indices.contract import DerivedIndex


def _find_ft3_ft4_tsh(text: str) -> tuple[Optional[float], Optional[float], Optional[float]]:
    if not text:
        return None, None, None
    low = text.lower().replace(",", ".")
    tsh = _extract_marker(low, [r"ттг\s*[:\s]*(\d+\.?\d*)", r"tsh\s*[:\s]*(\d+\.?\d*)"])
    ft3 = _extract_marker(low, [r"(?:св\.?\s*)?т3\s*[:\s]*(\d+\.?\d*)", r"ft3\s*[:\s]*(\d+\.?\d*)", r"трийодтиронин\s+свободн[^\d]*(\d+\.?\d*)"])
    ft4 = _extract_marker(low, [r"(?:св\.?\s*)?т4\s*[:\s]*(\d+\.?\d*)", r"ft4\s*[:\s]*(\d+\.?\d*)", r"тироксин\s+свободн[^\d]*(\d+\.?\d*)"])
    return ft3, ft4, tsh


def _extract_marker(low: str, patterns: List[str]) -> Optional[float]:
    for p in patterns:
        m = re.search(p, low)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return None


def compute_iti(text: str) -> DerivedIndex:
    """ИТИ только если есть все три показателя (в одних условных единицах в документе)."""
    ft3, ft4, tsh = _find_ft3_ft4_tsh(text)
    miss: List[str] = []
    if ft3 is None:
        miss.append("св. T3 (fT3)")
    if ft4 is None:
        miss.append("св. T4 (fT4)")
    if tsh is None:
        miss.append("ТТГ (TSH)")
    if miss:
        return DerivedIndex(
            code="iti",
            title="ИТИ (интегральный тиреоидный индекс)",
            required_markers=["ft3", "ft4", "tsh"],
            missing_markers=miss,
            confidence="supportive",
            patient_visible=False,
            interpretation="ИТИ = (fT3 + fT4) / ТТГ при согласованных единицах; без полного набора гормонов не считается.",
            not_calculated_reason="missing_thyroid_markers",
        )
    if tsh <= 0:
        return DerivedIndex(
            code="iti",
            title="ИТИ (интегральный тиреоидный индекс)",
            required_markers=["ft3", "ft4", "tsh"],
            missing_markers=["корректный ТТГ > 0"],
            confidence="supportive",
            not_calculated_reason="invalid_tsh",
        )
    iti = (ft3 + ft4) / tsh
    return DerivedIndex(
        code="iti",
        title="ИТИ (интегральный тиреоидный индекс)",
        value=round(iti, 4),
        unit="усл. ед.",
        status="расчёт выполнен",
        interpretation="Смысл зависит от единиц fT3/fT4 в бланке; сопоставление только с референсом лаборатории.",
        required_markers=["ft3", "ft4", "tsh"],
        confidence="supportive",
        patient_visible=False,
    )
