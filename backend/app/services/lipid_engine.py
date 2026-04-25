"""Движок для обработки липидного профиля (LDL, HDL, триглицериды, общий холестерин)."""
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.apob_lab_context import (
    apoa1_abnormal_table_row,
    apoa1_group_row,
    apoa1_hypothesis,
    apob_abnormal_table_row,
    apob_apoa1_ratio_interpretation,
    apob_group_row,
    apob_hypothesis,
    apob_marker_mentioned,
    atherogenic_lipid_signal,
    ensure_apob_followup_row,
    extract_apoa1_value_and_refs_g_l,
    extract_apob_g_per_l,
    extract_apob_reference_range_g_l,
    prepend_lipid_group_rows,
)

# Диапазон типичных значений в ммоль/л (не годы вроде 2025)
_LIPID_MIN = 0.15
_LIPID_MAX = 20.0
# Верхний ориентир «оптимума» ЛПНП на многих РФ-бланках (<3,0); не смешивать без пометки со взрослыми ~3,3 ммоль/л
_LDL_HIGH_LAB_MMOL = 3.0
_NON_HDL_REF_HIGH_MMOL = 3.4


def _normalize_lipid_ocr_text(text: str) -> str:
    if not text:
        return ""
    t = (
        text.replace("\u00a0", " ")
        .replace("\ufeff", "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    t = re.sub(r"[ \t\f\v]+", " ", t)
    return t


def _parse_lip_float(raw: str) -> Optional[float]:
    try:
        v = float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    if _LIPID_MIN <= v <= _LIPID_MAX:
        return v
    return None


def _result_mmol_before_comparison_op(tail: str) -> Optional[float]:
    """
    Бланки вида «6,09 < 3,00 ммоль/л» или «2,41 > 1,20 ммоль/л» — единица в конце строки,
    её нельзя привязывать только ко второму числу (референсу).
    Берём последнее число слева от первого оператора сравнения — обычно это результат.
    """
    low = (tail or "").replace("\u00a0", " ")
    m = re.search(r"\s*(?:<=|>=|[<≤>≥])\s*", low)
    if not m:
        return None
    left = low[: m.start()]
    nums = list(re.finditer(r"(\d+[,.]\d+|\d+)", left))
    if not nums:
        return None
    for nm in reversed(nums):
        v = _parse_lip_float(nm.group(1))
        if v is not None:
            return v
    return None


def _first_mmol_value_ref_range_at_end(tail: str) -> Optional[float]:
    """
    «9,54 3,50 - 6,20 ммоль/л» — результат, затем диапазон и одна «ммоль/л» в конце.
    """
    low = (tail or "").replace("\u00a0", " ")
    m = re.search(
        r"(\d+[,.]\d+|\d+)\s+(\d+[,.]\d+|\d+)\s*[-–]\s*(\d+[,.]\d+|\d+)\s*(?:ммоль|mmol|ммол)",
        low,
        re.IGNORECASE,
    )
    if not m:
        return None
    return _parse_lip_float(m.group(1))


def _is_mmol_number_after_less_than(tail: str, num_start: int) -> bool:
    """Число сразу после «<» или «≤» в той же строке — типично граница референса, если ммоль стоит после него."""
    before = tail[:num_start].rstrip()
    return bool(re.search(r"[<≤]\s*$", before))


def _is_likely_ref_upper_bound_before_number(full_text: str, abs_index: int) -> bool:
    """
    True, если цифра на abs_index начинает число сразу после «<» / «≤» — типично верхняя граница референса («< 3,00»),
    а не результат ЛПНП (например «6,09 ммоль/л < 3,00»).
    """
    if abs_index <= 0:
        return False
    prev = full_text[max(0, abs_index - 5) : abs_index]
    prev_st = prev.strip()
    if not prev_st:
        return False
    # «< 3» / «≤3» / «<3,00»
    if prev_st.endswith("<") or prev_st.endswith("≤") or prev_st.endswith("<=") or prev_st.endswith("≤="):
        return True
    if re.search(r"<\s*$|[≤]\s*$", prev):
        return True
    return False


def _best_mmol_value_in_tail(tail: str) -> Optional[float]:
    """
    Выбирает результат анализа в ммоль/л, не путая с «< 3,00» в той же строке.
    Приоритет: число с явной припиской ммоль/mmol; иначе первое число не после оператора сравнения.
    """
    # 0) «результат < реф ммоль/л» / «результат > реф ммоль/л» — ммоль одна на всю строку
    v_cmp = _result_mmol_before_comparison_op(tail)
    if v_cmp is not None:
        return v_cmp
    # 0b) «результат ref_lo - ref_hi ммоль/л»
    v_rng = _first_mmol_value_ref_range_at_end(tail)
    if v_rng is not None:
        return v_rng
    # 1) Явная связка с единицами — пропускать число, если оно граница после «<»/«≤»
    for mm in re.finditer(
        r"(\d+[,.]\d+|\d+)\s*(?:ммоль|mmol|ммол)",
        tail,
        re.IGNORECASE,
    ):
        if _is_mmol_number_after_less_than(tail, mm.start(1)):
            continue
        v = _parse_lip_float(mm.group(1))
        if v is not None:
            return v
    # 2) Десятичные числа по порядку, пропуская типичный хвост референса
    for num in re.finditer(r"(\d+[,.]\d+)", tail):
        if _is_likely_ref_upper_bound_before_number(tail, num.start(1)):
            continue
        v = _parse_lip_float(num.group(1))
        if v is not None:
            return v
    # 3) Целые (осторожно: «< 3» даёт 3 — пропускаем если перед числом <)
    for num in re.finditer(r"(?<![\d,])(\d{1,2})(?![\d,\.])", tail):
        if _is_likely_ref_upper_bound_before_number(tail, num.start(1)):
            continue
        v = _parse_lip_float(num.group(1))
        if v is not None and v >= _LIPID_MIN:
            return v
    return None


def _lipid_tail_after_label(low: str, end_pos: int, max_len: int = 200) -> str:
    """
    Хвост только до конца строки бланка (или max_len), чтобы не захватывать следующую строку
    («Общий холестерин …» + «Холестерин-ЛПНП …» в одном tail давало ложное 6,09 вместо 9,54).
    """
    chunk = low[end_pos : end_pos + max_len]
    return chunk.split("\n", 1)[0]


def _first_value_after_label(
    haystack: str,
    label_rx: re.Pattern,
) -> Optional[float]:
    """Ищет значение в ммоль/л после метки; не принимает границу референса («< 3,00») за результат."""
    low = haystack.lower()
    for m in label_rx.finditer(low):
        tail = _lipid_tail_after_label(low, m.end())
        v = _best_mmol_value_in_tail(tail)
        if v is not None:
            return v
    return None


def parse_lipid_values(text: str) -> Dict[str, Optional[float]]:
    """
    Извлекает значения липидного профиля из текста.
    Ищет: LDL (ЛПНП), HDL (ЛПВП), триглицериды, общий холестерин.
    Учитывает типичные РФ-бланки: между названием и результатом часто стоит «ммоль/л».
    """
    norm = _normalize_lipid_ocr_text(text)
    text_lower = norm.lower()
    values: Dict[str, Optional[float]] = {
        "ldl": None,
        "hdl": None,
        "triglycerides": None,
        "total_cholesterol": None,
    }

    # Сначала форматы ГБУЗ/МНПЦЛИ («Определение … общих 0.72»), иначе референс 0.10–2.30 даёт ложное ТГ.
    collapsed = re.sub(r"\s+", " ", text_lower.strip())
    _fill_lipids_from_rf_complex_table(collapsed, values)

    # Метки → ключ; порядок важен для строк с несколькими словами «холестерин»
    _LABELS: List[Tuple[str, re.Pattern]] = [
        (
            "total_cholesterol",
            re.compile(
                r"(?:^|\n|[^\wа-яё])"
                r"(?:общий\s+холестерин|холестерин\s+общий|холестерина\s+общий"
                r"|хс\s*общ|холестерин\s*\([^)]*общ[^)]*\)"
                r"|total\s+cholesterol|cholesterol\s*,?\s*total"
                r")(?:\s*\([^)]*\))?",
                re.IGNORECASE,
            ),
        ),
        (
            "ldl",
            re.compile(
                r"(?:^|\n|[^\wа-яё])"
                r"(?:лпнп|ldl\b|холестерин\s*лпнп|холестерин\s*[-–]?\s*лпнп"
                r"|лпнп[-\s]*холестерин|холестерин\s+низк(?:ой|ая)?\s+плотности"
                r"|low[\s-]*density[\s-]*lipoprotein)"
                r"(?:\s*\([^)]*\))?",
                re.IGNORECASE,
            ),
        ),
        (
            "hdl",
            re.compile(
                # Не матчить «лпвп» внутри «не-лпвп» / «не лпвп» (дефис перед лпвп)
                r"(?:^|\n|[^\wа-яё-])"
                r"(?:лпвп|hdl\b|холестерин\s*лпвп|холестерин\s*[-–]?\s*лпвп"
                r"|лпвп[-\s]*холестерин|холестерин\s+высок(?:ой|ая)?\s+плотности"
                r"|high[\s-]*density[\s-]*lipoprotein)"
                r"(?:\s*\([^)]*\))?",
                re.IGNORECASE,
            ),
        ),
        (
            "triglycerides",
            re.compile(
                r"(?:^|\n|[^\wа-яё])"
                r"(?:триглицерид[ы]?|триглицериды|triglycerides?\b|\bтг\b"
                r"|тг-?к|tg\b)"
                r"(?:\s*\([^)]*\))?",
                re.IGNORECASE,
            ),
        ),
    ]

    for key, rx in _LABELS:
        if values.get(key) is not None:
            continue
        v = _first_value_after_label(text_lower, rx)
        if v is not None:
            values[key] = v

    # Резерв: старые «плотные» шаблоны (цифра сразу после двоеточия)
    patterns = {
        "ldl": [
            r"лпнп\D{0,40}?(\d+[,.]\d+|\d+)",
            r"ldl\D{0,30}?(\d+[,.]\d+|\d+)",
        ],
        "hdl": [
            r"(?<![-–/])лпвп\D{0,40}?(\d+[,.]\d+|\d+)",
            r"hdl\D{0,30}?(\d+[,.]\d+|\d+)",
        ],
        "triglycerides": [
            r"триглицерид[ы]?\D{0,40}?(\d+[,.]\d+|\d+)",
            r"\bтг\D{0,20}?(\d+[,.]\d+|\d+)",
        ],
        "total_cholesterol": [
            r"общий\s+холестерин\D{0,60}?(\d+[,.]\d+|\d+)",
            r"холестерин\s+общий\D{0,60}?(\d+[,.]\d+|\d+)",
        ],
    }

    for key, pattern_list in patterns.items():
        if values.get(key) is not None:
            continue
        for pattern in pattern_list:
            for match in re.finditer(pattern, text_lower, re.IGNORECASE):
                try:
                    abs_start = match.start(1)
                    if _is_likely_ref_upper_bound_before_number(text_lower, abs_start):
                        continue
                    val_float = _parse_lip_float(match.group(1))
                    if val_float is not None:
                        values[key] = val_float
                        break
                except (ValueError, IndexError):
                    continue
            if values[key] is not None:
                break

    # Построчно: если показатель на своей строке, а число справа (таблица)
    if any(v is None for v in values.values()):
        for raw_line in norm.splitlines():
            line = raw_line.strip()
            if not line or len(line) > 220:
                continue
            low_ln = line.lower()
            for key, rx in _LABELS:
                if values.get(key) is not None:
                    continue
                mlab = rx.search(low_ln)
                if not mlab:
                    continue
                tail_ln = low_ln[mlab.end() :]
                v = _best_mmol_value_in_tail(tail_ln)
                if v is not None:
                    values[key] = v
                    continue
                # Без «ммоль» не брать числа со строки, похожей на дату (24.12.2025)
                if re.search(r"\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}", low_ln):
                    continue

    # Не-ЛПВП (non-HDL) — расчётный холестерин на многих бланках
    if values.get("non_hdl") is None:
        for rx in (
            # После заголовка часто идёт «Метод: расчётный», затем строка «Расчет N ммоль/л»
            r"не[-\s]?лпвп[\s\S]{0,420}?(\d+[,.]\d+|\d+)\s*ммоль/л",
            r"не[-\s]?лпвп[^0-9]{0,160}?(\d+[,.]\d+|\d+)\s*(?:ммоль|mmol|ммол)",
            r"non[\s\-]hdl[^0-9]{0,120}?(\d+[,.]\d+|\d+)\s*(?:ммоль|mmol|ммол)",
            r"холестерол\s*-\s*не[-\s]?лпвп[^0-9]{0,160}?(\d+[,.]\d+|\d+)\s*(?:ммоль|mmol|ммол)",
        ):
            nm = re.search(rx, text_lower, re.IGNORECASE)
            if nm:
                vnh = _parse_lip_float(nm.group(1))
                if vnh is not None:
                    values["non_hdl"] = vnh
                    break

    return values


def _fill_lipids_from_rf_complex_table(collapsed: str, values: Dict[str, Optional[float]]) -> None:
    """Достаёт результаты из свёрнутого текста вида «Определение холестерина общего 8.07»."""
    if not collapsed:
        return

    def _set(key: str, m: Any) -> None:
        if not m or values.get(key) is not None:
            return
        v = _parse_lip_float(m.group(1))
        if v is not None:
            values[key] = v

    _set(
        "triglycerides",
        re.search(
            r"определение\s+триглицеридов\s+общих?\s+(\d+[,.]\d+|\d+)\b",
            collapsed,
        ),
    )
    _set(
        "hdl",
        re.search(
            r"определение\s+липопротеинов\s+высокой\s+плотности\s*\([^)]*\)\s*(\d+[,.]\d+|\d+)\b",
            collapsed,
        ),
    )
    _set(
        "hdl",
        re.search(
            r"липопротеинов\s+высокой\s+плотности\s*\([^)]*лпвп[^)]*\)\s*(\d+[,.]\d+|\d+)\b",
            collapsed,
        ),
    )
    _set(
        "ldl",
        re.search(
            r"определение\s+липопротеинов\s+низкой\s+плотности\s*\([^)]*\)\s*(\d+[,.]\d+|\d+)\b",
            collapsed,
        ),
    )
    _set(
        "ldl",
        re.search(
            r"липопротеинов\s+низкой\s+плотности\s*\([^)]*лпнп[^)]*\)\s*(\d+[,.]\d+|\d+)\b",
            collapsed,
        ),
    )
    _set(
        "total_cholesterol",
        re.search(
            r"определение\s+холестерин\w*\s+общ\w+\s+(\d+[,.]\d+|\d+)\b",
            collapsed,
        ),
    )
    _set(
        "total_cholesterol",
        re.search(
            r"холестерин\w*\s+общ\w+\s+(\d+[,.]\d+|\d+)\b(?!\s*(?:ммоль|ммол|mmol))",
            collapsed,
        ),
    )


def build_lipid_hypotheses(values: Dict[str, Optional[float]]) -> List[Dict[str, str]]:
    """Строит гипотезы на основе значений липидного профиля."""
    hypotheses = []

    ldl = values.get("ldl")
    hdl = values.get("hdl")
    triglycerides = values.get("triglycerides")
    total = values.get("total_cholesterol")

    if ldl is not None:
        if ldl > 5.0:
            hypotheses.append({
                "hypothesis": "Высокий сердечно-сосудистый риск (выраженное повышение ЛПНП)",
                "basis": (
                    f"LDL {ldl:.2f} ммоль/л (на многих РФ-бланках ориентир <{_LDL_HIGH_LAB_MMOL} ммоль/л; "
                    "при >5 — высокий риск)"
                ),
                "comment": "Требует дообследования и оценки атерогенного риска",
            })
        elif ldl > _LDL_HIGH_LAB_MMOL:
            hypotheses.append({
                "hypothesis": "Повышен LDL (плохой холестерин)",
                "basis": (
                    f"LDL {ldl:.2f} ммоль/л (часто на бланке целевой ориентир <{_LDL_HIGH_LAB_MMOL} ммоль/л; "
                    "у взрослых иногда до ~3,3 ммоль/л — сверять с референсом лаборатории)"
                ),
                "comment": "Может указывать на атерогенный профиль и риск сердечно-сосудистых заболеваний",
            })
        elif ldl < 1.0:
            hypotheses.append({
                "hypothesis": "Снижен LDL",
                "basis": f"LDL {ldl:.2f} ммоль/л",
                "comment": "Требует оценки в контексте общего состояния",
            })

    nh = values.get("non_hdl")
    if nh is not None and nh > _NON_HDL_REF_HIGH_MMOL:
        hypotheses.append({
            "hypothesis": "Повышен холестерин не-ЛПВП (non-HDL)",
            "basis": f"Non-HDL {nh:.2f} ммоль/л (частый ориентир <{_NON_HDL_REF_HIGH_MMOL} ммоль/л при умеренном риске)",
            "comment": "Дополняет оценку атерогенной нагрузки наряду с ЛПНП; у детей — только с врачом",
        })

    if total is not None:
        if total > 7.0:
            hypotheses.append({
                "hypothesis": "Выраженная гиперхолестеринемия",
                "basis": f"Общий холестерин {total:.2f} ммоль/л (норма до 5.2)",
                "comment": "Высокий атерогенный риск; требуется оценка причины и тактики",
            })
        elif total > 5.2:
            hypotheses.append({
                "hypothesis": "Повышен общий холестерин",
                "basis": f"Общий холестерин {total:.2f} ммоль/л (норма до 5.2)",
                "comment": "Требует оценки соотношения LDL/HDL и триглицеридов",
            })

    if hdl is not None:
        if hdl < 1.0:
            hypotheses.append({
                "hypothesis": "Снижен HDL (хороший холестерин)",
                "basis": f"HDL {hdl:.2f} ммоль/л (желательно > 1.0)",
                "comment": "Может снижать защиту от атеросклероза",
            })
        elif hdl >= 1.5:
            hypotheses.append({
                "hypothesis": "Хороший уровень HDL",
                "basis": f"HDL {hdl:.2f} ммоль/л",
                "comment": "Положительный фактор",
            })

    if triglycerides is not None:
        if triglycerides > 1.7:
            hypotheses.append({
                "hypothesis": "Повышенные триглицериды",
                "basis": f"Триглицериды {triglycerides:.2f} ммоль/л (норма до 1.7)",
                "comment": "Может указывать на метаболические нарушения",
            })

    # Комплексная оценка
    if ldl and hdl and total:
        ratio = ldl / hdl if hdl > 0 else None
        if ratio and ratio > 3.0:
            hypotheses.append({
                "hypothesis": "Неблагоприятное соотношение LDL/HDL",
                "basis": f"LDL/HDL = {ratio:.2f} (желательно < 3.0)",
                "comment": "Повышенный атерогенный риск",
            })

    return hypotheses


def _lipid_values_present(values: Dict[str, Optional[float]]) -> bool:
    return any(v is not None for v in values.values())


def _build_lipid_grouped_interpretation(
    values: Dict[str, Optional[float]],
) -> List[Dict[str, str]]:
    """Строки для «Клиническая интерпретация по группам» (в т.ч. при норме)."""
    rows: List[Dict[str, str]] = []
    tc = values.get("total_cholesterol")
    if tc is not None:
        if tc > 5.2:
            interp = (
                f"ОХ {tc:.2f} ммоль/л — выше типичного верхнего предела (~5.2); "
                "целевые значения задаются по кардиориску."
            )
        elif tc > 4.5:
            interp = (
                f"ОХ {tc:.2f} ммоль/л — у верхней границы или в «серой» зоне; "
                "сопоставить с ЛПНП/ЛПВП и клиникой."
            )
        else:
            interp = (
                f"ОХ {tc:.2f} ммоль/л — без признаков выраженной гиперхолестеринемии "
                "по распространённым порогам."
            )
        rows.append({"group": "Общий холестерин (ОХ)", "interpretation": interp})

    ldl = values.get("ldl")
    if ldl is not None:
        if ldl > _LDL_HIGH_LAB_MMOL:
            interp = (
                f"ЛПНП {ldl:.2f} ммоль/л — выше типичного лабораторного ориентира <{_LDL_HIGH_LAB_MMOL} ммоль/л "
                "на многих бланках РФ; у взрослых иногда используют ~3,3 ммоль/л — сверять с референсом; "
                "тактика и цели — индивидуально (риск ССЗ, у подростков — педиатр)."
            )
        elif ldl >= 2.6:
            interp = (
                f"ЛПНП {ldl:.2f} ммоль/л — умеренный уровень; при высоком риске цели могут быть ниже."
            )
        else:
            interp = (
                f"ЛПНП {ldl:.2f} ммоль/л — в зоне, часто расцениваемой как приемлемая при отсутствии высокого риска."
            )
        rows.append({"group": "ЛПНП (LDL)", "interpretation": interp})

    nh = values.get("non_hdl")
    if nh is not None:
        if nh > _NON_HDL_REF_HIGH_MMOL:
            nhi = (
                f"Не-ЛПВП (non-HDL) {nh:.2f} ммоль/л — выше распространённого ориентира <{_NON_HDL_REF_HIGH_MMOL} ммоль/л "
                "для умеренного кардиориска на части бланков; сопоставить с ЛПНП и клиникой."
            )
        else:
            nhi = (
                f"Не-ЛПВП (non-HDL) {nh:.2f} ммоль/л — без превышения типичного ориентира <{_NON_HDL_REF_HIGH_MMOL} ммоль/л."
            )
        rows.append({"group": "Холестерин не-ЛПВП (non-HDL)", "interpretation": nhi})

    hdl = values.get("hdl")
    if hdl is not None:
        if hdl < 1.0:
            interp = (
                f"ЛПВП {hdl:.2f} ммоль/л — ниже желаемого порога (>1.0 ммоль/л у мужчин, "
                "часто >1.2 у женщин)."
            )
        elif hdl >= 1.5:
            interp = (
                f"ЛПВП {hdl:.2f} ммоль/л — благоприятный фактор с точки зрения атерогенного риска."
            )
        else:
            interp = (
                f"ЛПВП {hdl:.2f} ммоль/л — в пределах или около распространённых ориентиров."
            )
        rows.append({"group": "ЛПВП (HDL)", "interpretation": interp})

    tg = values.get("triglycerides")
    if tg is not None:
        if tg > 1.7:
            interp = (
                f"Триглицериды {tg:.2f} ммоль/л — выше порога 1.7 ммоль/л, связанного с метаболическим риском."
            )
        elif tg > 1.2:
            interp = (
                f"Триглицериды {tg:.2f} ммоль/л — ближе к верхней границе оптимального диапазона."
            )
        else:
            interp = (
                f"Триглицериды {tg:.2f} ммоль/л — в типичном целевом диапазоне (ориентир ≤1.7 ммоль/л)."
            )
        rows.append({"group": "Триглицериды", "interpretation": interp})

    return rows[:10]


def _baseline_lipid_followup() -> List[Dict[str, str]]:
    return [
        {
            "direction": "Наблюдение",
            "check": "Повторный липидный профиль через 6–12 мес при низком/умеренном риске",
            "why": "Динамика и индивидуальные целевые уровни",
            "priority": "Низкий",
        },
        {
            "direction": "Стратификация риска (по показаниям врача)",
            "check": "Аполипопротеин B (ApoB), г/л; липопротеин(a); при факторах риска — глюкоза, HbA1c",
            "why": (
                "ApoB отражает число атерогенных липопротеиновых частиц; при дислипидемии и метаболическом риске "
                "часто дополняет ЛПНП-ХС. Lp(a) — наследуемый независимый риск."
            ),
            "priority": "По клинике",
        },
        {
            "direction": "Образ жизни",
            "check": "Питание, физическая активность, контроль массы тела, отказ от курения",
            "why": "Базовая модификация липидного профиля и СС-риска",
            "priority": "Средний",
        },
    ]


def build_lipid_report(
    doc: Dict[str, Any],
    extracted_text: str,
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Строит отчёт по липидному профилю.
    Возвращает структуру, совместимую с document_physician_report.
    """
    values = parse_lipid_values(extracted_text)
    has_vals = _lipid_values_present(values)
    ext = extracted_text or ""
    apob_g = extract_apob_g_per_l(ext)
    apob_m = apob_marker_mentioned(ext)
    apob_ref_lo, apob_ref_hi = extract_apob_reference_range_g_l(ext)
    apoa1_g, apoa1_ref_lo, apoa1_ref_hi = extract_apoa1_value_and_refs_g_l(ext)
    ather = atherogenic_lipid_signal(
        values.get("ldl"),
        values.get("total_cholesterol"),
        values.get("triglycerides"),
        values.get("hdl"),
    )

    hypotheses = list(build_lipid_hypotheses(values))
    if apob_g is not None:
        hypotheses.insert(0, apob_hypothesis(apob_g, ref_low=apob_ref_lo, ref_high=apob_ref_hi))
    if apoa1_g is not None:
        hypotheses.insert(0, apoa1_hypothesis(apoa1_g, ref_low=apoa1_ref_lo, ref_high=apoa1_ref_hi))
    if not hypotheses and has_vals:
        hypotheses.append({
            "hypothesis": "Липидный спектр без выраженных отклонений от распространённых лабораторных порогов",
            "basis": "ОХ, ЛПНП, ЛПВП, ТГ по извлечённым значениям",
            "comment": "Целевые уровни и тактика — по абсолютному СС-риску и клинике, не по одному анализу.",
        })

    filename = doc.get("filename") or "липидный профиль"

    # Аномальные находки
    abnormal = []
    if values.get("ldl") and values["ldl"] > _LDL_HIGH_LAB_MMOL:
        abnormal.append({
            "marker": "LDL (ЛПНП)",
            "value": f"{values['ldl']:.2f}",
            "ref_low": "0",
            "ref_high": str(_LDL_HIGH_LAB_MMOL),
            "direction": "high",
            "comment": "Повышен (ориентир как на многих бланках <3,0 ммоль/л)",
        })
    if values.get("non_hdl") and values["non_hdl"] > _NON_HDL_REF_HIGH_MMOL:
        abnormal.append({
            "marker": "Холестерин не-ЛПВП (non-HDL)",
            "value": f"{values['non_hdl']:.2f}",
            "ref_low": "0",
            "ref_high": str(_NON_HDL_REF_HIGH_MMOL),
            "direction": "high",
            "comment": "Повышен (типичный ориентир на бланке <3,4 ммоль/л)",
        })
    if values.get("total_cholesterol") and values["total_cholesterol"] > 5.2:
        abnormal.append({
            "marker": "Общий холестерин",
            "value": f"{values['total_cholesterol']:.2f}",
            "ref_low": "0",
            "ref_high": "5.2",
            "direction": "high",
            "comment": "Повышен",
        })
    if values.get("hdl") and values["hdl"] < 1.0:
        abnormal.append({
            "marker": "HDL (ЛПВП)",
            "value": f"{values['hdl']:.2f}",
            "ref_low": "1.0",
            "ref_high": "—",
            "direction": "low",
            "comment": "Снижен",
        })
    if values.get("triglycerides") and values["triglycerides"] > 1.7:
        abnormal.append({
            "marker": "Триглицериды",
            "value": f"{values['triglycerides']:.2f}",
            "ref_low": "0",
            "ref_high": "1.7",
            "direction": "high",
            "comment": "Повышен",
        })
    if apob_g is not None:
        ab_ap = apob_abnormal_table_row(
            apob_g,
            ref_low=apob_ref_lo,
            ref_high=apob_ref_hi,
        )
        if ab_ap.get("direction") in ("high", "low"):
            abnormal.append(ab_ap)
    if apoa1_g is not None:
        ab_a1 = apoa1_abnormal_table_row(
            apoa1_g,
            ref_low=apoa1_ref_lo,
            ref_high=apoa1_ref_hi,
        )
        if ab_a1.get("direction") in ("high", "low"):
            abnormal.append(ab_a1)

    # Рекомендации по проверкам
    followup = []
    if values.get("ldl") and values["ldl"] > _LDL_HIGH_LAB_MMOL:
        if apob_g is None:
            followup.append({
                "direction": "Липидный профиль",
                "check": "Аполипопротеин B (ApoB), липопротеин(a)",
                "why": "При повышенном ЛПНП — число атерогенных частиц (ApoB) и наследуемый Lp(a).",
                "priority": "Средний",
            })
        else:
            followup.append({
                "direction": "Липидный профиль",
                "check": "Липопротеин(a); динамика ApoB под терапией",
                "why": "ЛПНП повышен; ApoB на бланке — при необходимости Lp(a) и контроль эффекта лечения.",
                "priority": "Средний",
            })
    if values.get("total_cholesterol") and values["total_cholesterol"] > 5.2:
        followup.append({
            "direction": "Метаболический профиль",
            "check": "Глюкоза, инсулин, HbA1c",
            "why": "Оценка метаболического статуса",
            "priority": "Средний",
        })

    grouped = _build_lipid_grouped_interpretation(values) if has_vals else []
    if not followup and has_vals:
        followup = _baseline_lipid_followup()
    ensure_apob_followup_row(
        followup,
        has_lipid_values=has_vals,
        apob_g=apob_g,
        atherogenic=ather,
    )
    if has_vals:
        g_apob = apob_group_row(
            has_lipid_values=True,
            apob_g=apob_g,
            mentioned=apob_m,
        )
        extra_grp: List[Dict[str, str]] = []
        if g_apob:
            extra_grp.append(g_apob)
        if apoa1_g is not None:
            extra_grp.append(
                apoa1_group_row(
                    apoa1_g,
                    ref_low=apoa1_ref_lo,
                    ref_high=apoa1_ref_hi,
                )
            )
        if apob_g is not None and apoa1_g is not None:
            ratio_g = apob_apoa1_ratio_interpretation(apob_g, apoa1_g)
            if ratio_g:
                extra_grp.append(ratio_g)
        grouped = prepend_lipid_group_rows(grouped, extra_grp)

    # Краткий вывод
    summary_lines: List[str] = []
    if has_vals:
        if hypotheses:
            for h in hypotheses[:3]:
                summary_lines.append(h["hypothesis"])
        else:
            summary_lines.append(
                "По извлечённым показателям липидного спектра выраженных отклонений от распространённых порогов не выявлено."
            )
        if (
            values.get("hdl")
            and values["hdl"] >= 1.5
            and values.get("triglycerides")
            and values["triglycerides"] < 1.7
        ):
            summary_lines.append("HDL в норме, триглицериды в норме — положительные факторы.")

    clinical_unavailable = not has_vals
    limitations = [
        "Интерпретация липидного профиля требует учёта возраста, пола, факторов риска и клинической картины.",
    ]
    if has_vals:
        limitations.append(
            "При наличии липидных данных целесообразно учитывать аполипопротеин B (ApoB) как маркер числа атерогенных частиц "
            "и сопоставлять с ЛПНП, non-HDL и клиническим СС-риском."
        )
    if clinical_unavailable:
        limitations = ["—"]

    return {
        "doc_type": "lipid_panel",
        "document_type": "lipid_panel",
        "document_name": filename,
        "document_summary": {},
        "patient": {},
        "summary": summary_lines,
        "abnormal_findings": abnormal,
        "abnormal_markers_table": abnormal,
        "recommended_followup_table": followup,
        "top_hypotheses_table": hypotheses[:5],
        "grouped_interpretation_table": grouped,
        "interpretation": summary_lines,
        "follow_up": {
            "tests": [f["check"] for f in followup],
            "referrals": [],
            "notes": [
                "Оценка питания, физической активности и веса",
                "Индивидуальные целевые уровни липидов — по кардиориску и врачебной тактике",
                "ApoB (г/л): при дислипидемии и метаболическом риске предпочтительно определять наряду с классической липидной панелью.",
            ],
        },
        "limitations": limitations,
        "clinical_content_unavailable": clinical_unavailable,
        "professional_summary": _build_lipid_professional_summary(
            values,
            hypotheses,
            apob_g=apob_g,
            apoa1_g=apoa1_g,
            apob_apoa1_ratio=(
                (apob_g / apoa1_g) if (apob_g is not None and apoa1_g is not None and apoa1_g > 0) else None
            ),
        ),
    }


def _build_lipid_professional_summary(
    values: Dict[str, Optional[float]],
    hypotheses: List[Dict[str, str]],
    apob_g: Optional[float] = None,
    apoa1_g: Optional[float] = None,
    apob_apoa1_ratio: Optional[float] = None,
) -> str:
    """Строит текстовый профессиональный summary для липидного профиля."""
    parts = ["Липидный профиль"]
    parts.append("")

    if not _lipid_values_present(values):
        parts.append("Числовые значения из текста не извлечены — см. оригинал бланка.")
        return "\n".join(parts)

    if values.get("total_cholesterol"):
        parts.append(f"Общий холестерин: {values['total_cholesterol']:.2f} ммоль/л")
    if values.get("ldl"):
        parts.append(f"LDL (ЛПНП): {values['ldl']:.2f} ммоль/л")
    if values.get("hdl"):
        parts.append(f"HDL (ЛПВП): {values['hdl']:.2f} ммоль/л")
    if values.get("triglycerides"):
        parts.append(f"Триглицериды: {values['triglycerides']:.2f} ммоль/л")
    if values.get("non_hdl") is not None:
        parts.append(f"Не-ЛПВП (non-HDL): {values['non_hdl']:.2f} ммоль/л")
    if apob_g is not None:
        parts.append(f"Аполипопротеин B (ApoB): {apob_g:.2f} г/л")
    if apoa1_g is not None:
        parts.append(f"Аполипопротеин A1 (ApoA1): {apoa1_g:.2f} г/л")
    if apob_apoa1_ratio is not None:
        parts.append(
            f"Отношение ApoB/ApoA1: {apob_apoa1_ratio:.2f} (апоВ ÷ апоА1; интерпретация — с врачом и референсом лаборатории)"
        )
    parts.append("")

    if hypotheses:
        parts.append("Ключевые находки:")
        for h in hypotheses[:4]:
            parts.append(f"- {h['hypothesis']}: {h.get('comment', '')}")
    else:
        parts.append("Значимых отклонений не выявлено.")

    parts.append("")
    if apob_g is None:
        parts.append(
            "Рекомендации: оценка питания и активности; дообследование — аполипопротеин B (ApoB), липопротеин(a), глюкоза/инсулин по показаниям."
        )
    else:
        parts.append(
            "Рекомендации: оценка питания и активности; при необходимости — липопротеин(a), глюкоза/инсулин; динамика ApoB под терапией."
        )

    return "\n".join(parts)
