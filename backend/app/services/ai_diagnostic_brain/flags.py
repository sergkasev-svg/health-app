from __future__ import annotations

import re
from typing import Any, Dict, List


def _join_text(*parts: Any) -> str:
    chunks: List[str] = []
    for p in parts:
        if isinstance(p, list):
            chunks.extend([str(x or "") for x in p])
        else:
            chunks.append(str(p or ""))
    return " ".join(chunks).lower()


def _contains_all(text: str, needles: List[str]) -> bool:
    return all(n in text for n in needles)


def derive_lab_flags(report: Dict[str, Any]) -> List[str]:
    r = report if isinstance(report, dict) else {}
    text = _join_text(
        r.get("display_summary"),
        r.get("user_summary"),
        r.get("case_summary"),
        r.get("professional_summary"),
        r.get("findings"),
        r.get("hypotheses"),
        r.get("diagnostics"),
    )
    flags: List[str] = []

    # CBC / ESR
    if "сое" in text and any(x in text for x in ["ускор", "повыш", "high"]):
        flags.append("esr_high")

    # Lipids / LDL
    if any(x in text for x in ["лпнп", "ldl"]) and any(x in text for x in ["повыш", "high", "выраженн"]):
        flags.append("ldl_high")

    # Urine infection patterns
    if _contains_all(text, ["лейкоц"]) and any(x in text for x in ["полож", "повыш"]):
        flags.append("urine_leukocytes_positive")
        flags.append("urine_leukocytes_high")
    if _contains_all(text, ["нитрит"]) and any(x in text for x in ["полож", "повыш"]):
        flags.append("urine_nitrites_positive")

    # Stool inflammation
    if any(x in text for x in ["кальпротект", "calprotectin"]) and any(x in text for x in ["повыш", "high"]):
        flags.append("calprotectin_high")

    # Organic acids / mitochondrial markers
    if any(x in text for x in ["митох", "beta-окис", "β-окис", "энергообмен", "sebacic", "malonic", "pyroglutamic"]):
        flags.append("mitochondrial_markers")
    if any(x in text for x in ["figlu"]) and any(x in text for x in ["повыш", "high"]):
        flags.append("figlu_high")
    if any(x in text for x in ["methylmalonic", "метилмалон"]) and any(x in text for x in ["повыш", "high"]):
        flags.append("methylmalonic_high")

    # Fatty acids / integral indices by text markers
    if any(x in text for x in ["omega-3 index", "индекс омега-3"]) and any(x in text for x in ["низ", "low"]):
        flags.append("omega_3_low")
        flags.append("omega3_index_low")
    if any(x in text for x in ["aa/epa", "aa epa"]) and any(x in text for x in ["выс", "high"]):
        flags.append("aa_epa_high")
        flags.append("aa_epa_ratio_high")
    if any(x in text for x in ["omega-6/omega-3", "omega6/omega3"]) and any(x in text for x in ["выс", "high"]):
        flags.append("omega6_omega3_high")
        flags.append("omega6_3_ratio_high")

    # Integral indices from numeric report text if present
    # Total/HDL, TG/HDL, LDL/HDL (supports "x/y = 4.2")
    for key, code, thr in [
        ("total/hdl", "index_total_hdl_high", 4.5),
        ("tg/hdl", "index_tg_hdl_high", 2.0),
        ("ldl/hdl", "index_ldl_hdl_high", 3.0),
    ]:
        m = re.search(rf"{re.escape(key)}\s*[:=]?\s*([0-9]+(?:[.,][0-9]+)?)", text)
        if m:
            try:
                v = float(m.group(1).replace(",", "."))
                if v >= thr:
                    flags.append(code)
            except Exception:
                pass

    # keep order unique
    out: List[str] = []
    seen = set()
    for f in flags:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out
