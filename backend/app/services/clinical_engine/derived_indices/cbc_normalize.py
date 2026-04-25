"""
Нормализация List[LabValue] для расчётных индексов ОАК.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.services.lab_value_extractor import LabValue


def _get(rows: List[LabValue], marker: str) -> Optional[LabValue]:
    for v in rows:
        if v.marker == marker:
            return v
    return None


def _fv(lv: Optional[LabValue]) -> Optional[float]:
    return lv.value if lv is not None else None


def build_cbc_numeric_context(rows: List[LabValue]) -> Dict[str, Optional[float]]:
    """
    Возвращает:
      wbc, plt,
      neut_abs, lymph_abs, mono_abs, eos_pct, mon_pct, lymph_pct, seg_neut_pct, neut_pct
    При отсутствии абсолютных значений — оценка из WBC и % (если возможно).
    """
    wbc = _fv(_get(rows, "WBC"))
    plt = _fv(_get(rows, "PLT"))
    n_abs = _fv(_get(rows, "Neutrophils_abs"))
    l_abs = _fv(_get(rows, "Lymphocytes_abs"))
    m_abs = _fv(_get(rows, "Monocytes_abs"))
    n_pct = _fv(_get(rows, "Neutrophils"))
    l_pct = _fv(_get(rows, "Lymphocytes"))
    mon_pct = _fv(_get(rows, "Monocytes"))
    eos_pct = _fv(_get(rows, "Eosinophils"))
    seg_pct = _fv(_get(rows, "Segmented_neutrophils"))

    if n_abs is None and wbc is not None and n_pct is not None:
        n_abs = wbc * (n_pct / 100.0)
    if l_abs is None and wbc is not None and l_pct is not None:
        l_abs = wbc * (l_pct / 100.0)
    if m_abs is None and wbc is not None and mon_pct is not None:
        m_abs = wbc * (mon_pct / 100.0)

    if seg_pct is None and n_pct is not None:
        seg_pct = n_pct

    return {
        "wbc": wbc,
        "plt": plt,
        "neut_abs": n_abs,
        "lymph_abs": l_abs,
        "mono_abs": m_abs,
        "neut_pct": n_pct,
        "lymph_pct": l_pct,
        "mon_pct": mon_pct,
        "eos_pct": eos_pct,
        "seg_neut_pct": seg_pct,
    }
