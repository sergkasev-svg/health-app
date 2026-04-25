"""
Политика подачи для пациента: safety-first, clarity-first, anxiety-minimizing, action-oriented.
Без псевдодиагнозов, без назначения лечения; простой язык и чёткие действия.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.clinical_engine.contracts import ClinicalCoreResult, Finding, OverallRisk

# Простые названия показателей для пациента (без сырых кодов)
PATIENT_MARKER_LABELS: Dict[str, str] = {
    "total_cholesterol": "общий холестерин",
    "ldl_cholesterol": "«плохой» холестерин (ЛПНП)",
    "hdl_cholesterol": "«хороший» холестерин (ЛПВП)",
    "triglycerides": "триглицериды",
    "hba1c": "показатель сахара в крови за 3 месяца (HbA1c)",
    "fructosamine": "показатель, связанный с уровнем сахара за последние недели",
    "hs_crp": "показатель воспаления (hs-CRP)",
    "crp": "С-реактивный белок",
}


# Порядок маркеров в блоке «Что именно отклонено»
_DEVIATION_ORDER = ("total_cholesterol", "ldl_cholesterol", "fructosamine", "hba1c", "hdl_cholesterol", "triglycerides", "hs_crp", "crp")


def patient_finding_line(f: Finding, values_by_code: Dict[str, Any]) -> str:
    """Одно отклонение простыми словами; без диагноза. С точкой с запятой в конце для единообразия."""
    code = (f.primary_value_code or "").lower() or (f.supporting_markers[0] if f.supporting_markers else "")
    label = PATIENT_MARKER_LABELS.get(code, f.title.lower())
    # Явные формулировки для ключевых маркеров (независимо от severity)
    if code == "total_cholesterol":
        return "общий холестерин выше нормы;"
    if code == "ldl_cholesterol":
        return 'ЛПНП («плохой» холестерин) значительно выше нормы;'
    if code == "fructosamine":
        return "фруктозамин выше нормы;"
    if f.severity in ("high", "moderate", "critical"):
        return f"{label} выше нормы;"
    if f.severity in ("low",):
        return f"{label} ниже нормы;"
    return f"{label} вне обычного диапазона;"


def patient_what_deviated_lines(core: ClinicalCoreResult) -> List[str]:
    """
    Упорядоченный список строк «что именно отклонено» + при наличии фруктозамина и HbA1c — строка про HbA1c в референсе.
    """
    values = core.normalized_values or {}
    findings = core.final_findings or []
    has_fruct = any(
        (f.primary_value_code or "").lower() == "fructosamine" or "фруктозамин" in (f.title or "").lower()
        for f in findings
    )
    hba1c_val = values.get("hba1c")

    lines: List[str] = []
    seen_codes: set = set()
    for code in _DEVIATION_ORDER:
        for f in findings:
            c = (f.primary_value_code or "").lower()
            if c != code:
                continue
            if c in seen_codes:
                continue
            seen_codes.add(c)
            lines.append(patient_finding_line(f, values))
    for f in findings:
        c = (f.primary_value_code or "").lower()
        if c not in seen_codes:
            seen_codes.add(c)
            lines.append(patient_finding_line(f, values))

    if has_fruct and hba1c_val is not None:
        lines.append("показатель HbA1c находится в пределах референса.")

    return lines


def patient_main_point_from_core(core: ClinicalCoreResult) -> str:
    """
    «Главное» в 2–4 предложения: что видно по анализу и что делать.
    Не копирует physician summary; строит свой смысл из findings и risk.
    """
    parts: List[str] = []
    findings = core.final_findings or []
    risk = core.risk
    values = core.normalized_values or {}

    # Липиды
    has_ldl = any(
        (f.primary_value_code or "").lower() == "ldl_cholesterol" or "лпнп" in (f.title or "").lower()
        for f in findings
    )
    has_total = any(
        (f.primary_value_code or "").lower() == "total_cholesterol" or "холестерин" in (f.title or "").lower() and "лпнп" not in (f.title or "").lower()
        for f in findings
    )
    if has_ldl or has_total:
        parts.append(
            "В анализе крови есть заметное повышение холестерина, особенно ЛПНП («плохого» холестерина). "
            "Это важно обсудить с врачом, потому что такие изменения могут быть связаны с повышенным риском для сосудов и сердца."
        )

    # Углеводный обмен (фруктозамин)
    has_fruct = any(
        (f.primary_value_code or "").lower() == "fructosamine" or "фруктозамин" in (f.title or "").lower()
        for f in findings
    )
    if has_fruct:
        parts.append(
            "Также повышен один из показателей, связанных с уровнем сахара за последние недели, "
            "поэтому углеводный обмен стоит уточнить дополнительно."
        )

    if not parts:
        if findings:
            parts.append("В анализе есть отклонения от нормы. Их стоит обсудить с врачом.")
        else:
            parts.append("Результаты анализа требуют оценки врачом в контексте вашего состояния.")

    return " ".join(parts).strip()


def patient_next_step_line(step: Dict[str, Any]) -> str:
    """Один шаг в формате «обсудить …» / «показать врачу»; без назначения. Без точки с запятой — рендер добавит."""
    what = (step.get("check") or step.get("what") or "").strip()
    if not what:
        return "обсудить с врачом дальнейший план"
    what_lower = what.lower()
    if "липидограм" in what_lower or "липидограмма" in what_lower:
        return "обсудить повторную липидограмму натощак"
    if "липид" in what_lower and "липидограм" not in what_lower:
        return "обсудить повторную липидограмму натощак"
    if "apo" in what_lower or "non-hdl" in what_lower:
        return "обсудить дополнительные анализы липидного обмена"
    if "ттг" in what_lower:
        return "обсудить проверку функции щитовидной железы"
    if "глюкоз" in what_lower or "сахар" in what_lower:
        return "обсудить проверку глюкозы натощак"
    if "инсулин" in what_lower or "homa" in what_lower:
        return "по рекомендации врача — дополнительные анализы, связанные с углеводным обменом"
    if "оценк" in what_lower and "риск" in what_lower:
        return "обсудить с врачом оценку риска для сердца и сосудов"
    return f"обсудить с врачом: {what}"


def patient_red_flags(core: ClinicalCoreResult) -> List[str]:
    """Когда не ждать — красные флаги обычным языком."""
    urgency: List[str] = list(core.urgency or [])
    if core.risk and getattr(core.risk, "urgency", None):
        urgency.append(core.risk.urgency)
    if any(u in ("urgent", "emergent") for u in urgency if u):
        return [
            "Не откладывайте визит к врачу при появлении сильной слабости, одышки, боли в груди, "
            "резком ухудшении самочувствия или других тревожных симптомов."
        ]
    return [
        "Срочно обращаться за помощью нужно не из-за самого анализа, а если есть резкое ухудшение самочувствия, "
        "сильная боль в груди, выраженная одышка, слабость, спутанность сознания или другие опасные симптомы."
    ]


def patient_what_it_means(core: ClinicalCoreResult) -> str:
    """«Что это может значить» — осторожно, без диагноза. Для липидного профиля с фруктозамином — развёрнутый текст."""
    findings = core.final_findings or []
    has_lipid = any(
        (f.primary_value_code or "").lower() in ("ldl_cholesterol", "total_cholesterol") or "холестерин" in (f.title or "").lower()
        for f in findings
    )
    has_fruct = any(
        (f.primary_value_code or "").lower() == "fructosamine" or "фруктозамин" in (f.title or "").lower()
        for f in findings
    )
    if has_lipid and has_fruct:
        return (
            "Этот анализ сам по себе не ставит диагноз, но показывает, что жировой обмен требует внимания. "
            "Такие изменения не стоит игнорировать: их нужно обсудить с врачом и уточнить, насколько они стойкие и с чем могут быть связаны. "
            "Повышенный фруктозамин не означает автоматически диабет, но требует уточнения по дополнительным анализам."
        )
    if has_lipid:
        return (
            "Этот анализ сам по себе не ставит диагноз, но показывает, что жировой обмен требует внимания. "
            "Такие изменения не стоит игнорировать: их нужно обсудить с врачом и уточнить, насколько они стойкие и с чем могут быть связаны."
        )
    return (
        "Это не равно диагнозу. Результаты анализа показывают изменения, которые требуют обсуждения с врачом: "
        "только врач может оценить их в контексте вашего здоровья и назначить дальнейшие шаги."
    )
