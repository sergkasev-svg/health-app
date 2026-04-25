"""
Индексы на основе ОАК: NLR, SII, SIRI, AISI, индекс Гаркави, ИИР.

Пороги SII/SIRI — ориентиры из методички (часть 1); AISI — только число без жёсткой клиники.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.services.clinical_engine.derived_indices.contract import DerivedIndex
from app.services.clinical_engine.derived_indices.cbc_normalize import build_cbc_numeric_context
from app.services.lab_value_extractor import LabValue


def _nlr_status(nlr: float) -> str:
    if nlr < 2.0:
        return "низкий/спокойный уровень (ориентир)"
    if nlr <= 3.0:
        return "умеренный (ориентир)"
    return "повышен (воспалительный контекст не исключён)"


def _sii_band(sii: float) -> str:
    # методичка: <335, 335–468, 468–655, >655
    if sii < 335:
        return "низкий диапазон (<335)"
    if sii < 468:
        return "335–468"
    if sii < 655:
        return "468–655"
    return "≥655"


def _siri_band(siri: float) -> str:
    if siri < 0.68:
        return "низкий диапазон (<0.68)"
    if siri < 0.99:
        return "0.68–0.98"
    if siri < 1.43:
        return "0.99–1.42"
    return "≥1.43"


def compute_cbc_derived_indices(rows: List[LabValue]) -> List[DerivedIndex]:
    ctx = build_cbc_numeric_context(rows)
    out: List[DerivedIndex] = []
    neut_abs = ctx["neut_abs"]
    lymph_abs = ctx["lymph_abs"]
    mono_abs = ctx["mono_abs"]
    plt = ctx["plt"]
    lymph_pct = ctx["lymph_pct"]
    seg_pct = ctx["seg_neut_pct"]
    eos_pct = ctx["eos_pct"]
    mon_pct = ctx["mon_pct"]

    # NLR
    if neut_abs is None or lymph_abs is None or lymph_abs == 0:
        miss = []
        if neut_abs is None:
            miss.append("нейтрофилы (абс или % + WBC)")
        if lymph_abs is None:
            miss.append("лимфоциты (абс или % + WBC)")
        if lymph_abs == 0:
            miss.append("лимфоциты ≠ 0")
        out.append(
            DerivedIndex(
                code="nlr",
                title="NLR (нейтрофилы/лимфоциты)",
                required_markers=["neutrophils_abs", "lymphocytes_abs"],
                missing_markers=miss,
                confidence="supportive",
                not_calculated_reason="missing",
            )
        )
    else:
        nlr = neut_abs / lymph_abs
        out.append(
            DerivedIndex(
                code="nlr",
                title="NLR (нейтрофилы/лимфоциты)",
                value=round(nlr, 4),
                status=_nlr_status(nlr),
                interpretation="Ориентир воспалительного баланса; не заменяет клинику и другие маркеры.",
                required_markers=["neutrophils_abs", "lymphocytes_abs"],
                confidence="supportive",
                patient_visible=False,
            )
        )

    nlr_val: Optional[float] = None
    if neut_abs and lymph_abs and lymph_abs != 0:
        nlr_val = neut_abs / lymph_abs

    # SII, SIRI, AISI
    if nlr_val is None or plt is None:
        out.append(
            DerivedIndex(
                code="sii",
                title="SII (тромбоциты × NLR)",
                required_markers=["plt", "nlr"],
                missing_markers=["NLR или тромбоциты"],
                confidence="supportive",
                not_calculated_reason="missing",
            )
        )
    else:
        sii = plt * nlr_val
        out.append(
            DerivedIndex(
                code="sii",
                title="SII (тромбоциты × NLR)",
                value=round(sii, 2),
                status=_sii_band(sii),
                interpretation="Ориентир системного воспаления; зоны по методичке — справочно.",
                required_markers=["plt", "nlr"],
                confidence="supportive",
                patient_visible=False,
            )
        )

    if nlr_val is None or mono_abs is None:
        out.append(
            DerivedIndex(
                code="siri",
                title="SIRI (моноциты(абс) × NLR)",
                required_markers=["monocytes_abs", "nlr"],
                missing_markers=["NLR или моноциты (абс)"],
                confidence="supportive",
                not_calculated_reason="missing",
            )
        )
    else:
        siri = mono_abs * nlr_val
        out.append(
            DerivedIndex(
                code="siri",
                title="SIRI (моноциты(абс) × NLR)",
                value=round(siri, 4),
                status=_siri_band(siri),
                interpretation="Не подменяет оценку липидного риска; при SIRI >1.0 по методичке смотреть липиды/сосуды — у вас может быть иначе.",
                required_markers=["monocytes_abs", "nlr"],
                confidence="supportive",
                patient_visible=False,
            )
        )

    if nlr_val is None or plt is None or mono_abs is None:
        miss_aisi: List[str] = []
        if nlr_val is None:
            miss_aisi.append("NLR")
        if plt is None:
            miss_aisi.append("тромбоциты")
        if mono_abs is None:
            miss_aisi.append("моноциты (абс)")
        out.append(
            DerivedIndex(
                code="aisi",
                title="AISI (PLT × моноциты(абс) × NLR)",
                required_markers=["plt", "monocytes_abs", "nlr"],
                missing_markers=miss_aisi,
                confidence="supportive",
                not_calculated_reason="missing",
            )
        )
    else:
        aisi = plt * mono_abs * nlr_val
        out.append(
            DerivedIndex(
                code="aisi",
                title="AISI (PLT × моноциты(абс) × NLR)",
                value=round(aisi, 2),
                status="расчёт выполнен",
                interpretation="Универсальных порогов для бытового отчёта в методичке нет; число — справочно.",
                required_markers=["plt", "monocytes_abs", "nlr"],
                confidence="supportive",
                patient_visible=False,
            )
        )

    # Harkavi: lymph% / seg_neut%
    if lymph_pct is None or seg_pct is None or seg_pct == 0:
        out.append(
            DerivedIndex(
                code="harkavi_index",
                title="Индекс Гаркави (лимфоциты%% / сегментоядерные%%)",
                required_markers=["lymphocytes_pct", "segmented_neutrophils_pct"],
                missing_markers=["лимфоциты %% и/или сегментоядерные %%"],
                confidence="exploratory",
                interpretation="Авторский индекс; не mainstream. Показывается как дополнительный маркер.",
                not_calculated_reason="missing",
            )
        )
    else:
        h = lymph_pct / seg_pct
        if h < 0.29:
            st = "ниже 0.29 — сниженные адаптационные возможности (авторская шкала)"
        elif h > 0.51:
            st = "по авторской шкале выше зоны «нормальной стресс-реакции» (0.4–0.5)"
        else:
            st = "в зоне ориентиров (см. методичку)"
        out.append(
            DerivedIndex(
                code="harkavi_index",
                title="Индекс Гаркави (лимфоциты%% / сегментоядерные%%)",
                value=round(h, 4),
                status=st,
                interpretation="Не использовать как главный вывод; только в контексте клиники.",
                required_markers=["lymphocytes_pct", "segmented_neutrophils_pct"],
                confidence="exploratory",
                patient_visible=False,
            )
        )

    # IIR: (lymph% + eos%) / mon%
    if lymph_pct is None or eos_pct is None or mon_pct is None or mon_pct == 0:
        out.append(
            DerivedIndex(
                code="iir",
                title="ИИР ((лимфоциты%% + эозинофилы%%) / моноциты%%)",
                required_markers=["lymphocytes_pct", "eosinophils_pct", "monocytes_pct"],
                missing_markers=["формула в %%"],
                confidence="exploratory",
                not_calculated_reason="missing",
            )
        )
    else:
        iir = (lymph_pct + eos_pct) / mon_pct
        st = "ниже 18.1 (авторская шкала)" if iir < 18.1 else "в среднем/высоком диапазоне (ориентир)"
        out.append(
            DerivedIndex(
                code="iir",
                title="ИИР ((лимфоциты%% + эозинофилы%%) / моноциты%%)",
                value=round(iir, 4),
                status=st,
                interpretation="Авторский индекс; интерпретация осторожно.",
                required_markers=["lymphocytes_pct", "eosinophils_pct", "monocytes_pct"],
                confidence="exploratory",
                patient_visible=False,
            )
        )

    return out
