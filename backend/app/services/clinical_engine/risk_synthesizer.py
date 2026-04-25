"""
Синтез summary, working_hypotheses, next_steps и limitations из канонического списка findings.
Один источник правды — findings; остальные секции строятся из них.
"""
from __future__ import annotations

from typing import List, Tuple

from app.services.clinical_engine.contracts import Finding, LabValue


def _val(values: List[LabValue], code: str) -> LabValue | None:
    for v in values:
        if v.code == code:
            return v
    return None


def build_summary(findings: List[Finding], values: List[LabValue], profile: str) -> str:
    """
    Summary строится только из findings.
    При lipid_panel и наличии severe_hypercholesterolemia / marked_ldl_elevation
    summary обязан содержать клинически значимую дислипидемию / атерогенный риск.
    """
    high = [f for f in findings if f.severity == "high" and f.include_in_summary]
    moderate = [f for f in findings if f.severity == "moderate" and f.include_in_summary]
    mild = [f for f in findings if f.severity == "mild" and f.include_in_summary]

    parts: List[str] = []

    if not findings:
        return "Извлечённые показатели в пределах референса или недостаточно данных для клинического вывода. Рекомендуется очная оценка врача."

    # Обязательная формулировка по спеке при липидных high findings
    has_severe = any(f.code in ("severe_hypercholesterolemia", "marked_ldl_elevation") for f in high)
    if has_severe and profile == "lipid_panel":
        total = _val(values, "total_cholesterol")
        ldl = _val(values, "ldl_cholesterol")
        if total and ldl and total.value is not None and ldl.value is not None:
            line = f"Выявлена клинически значимая дислипидемия: общий холестерин {total.value:.2f} ммоль/л и ЛПНП {ldl.value:.2f} ммоль/л значительно выше референсных значений. Это соответствует выраженному атерогенному профилю и требует оценки сердечно-сосудистого риска и причин дислипидемии."
        else:
            line = "Выявлена клинически значимая дислипидемия. Это соответствует выраженному атерогенному профилю и требует оценки сердечно-сосудистого риска и причин дислипидемии."
        parts.append(line)

    for f in high:
        if f.code in ("severe_hypercholesterolemia", "marked_ldl_elevation") and has_severe and profile == "lipid_panel":
            continue
        parts.append(f.summary_text)

    # Фруктозамин при нормальном HbA1c — только value, никогда ref_high
    fruct_f = next((f for f in mild if f.code in ("fructosamine_elevated_with_normal_hba1c", "fructosamine_elevated")), None)
    fruct_v = _val(values, "fructosamine")
    hba1c_v = _val(values, "hba1c")
    if fruct_f:
        fruct_num = fruct_v.value if fruct_v and fruct_v.value is not None else None
        hba1c_num = hba1c_v.value if hba1c_v and getattr(hba1c_v, "value", None) is not None else None
        if fruct_num is not None and hba1c_num is not None:
            parts.append(
                f"Фруктозамин {fruct_num:.2f} мкмоль/л повышен при HbA1c {hba1c_num:.1f}% (в пределах референса), что требует сопоставления с показателями глюкозы крови и клиническим контекстом."
            )
        else:
            parts.append("Фруктозамин повышен при HbA1c в норме, что требует сопоставления с показателями глюкозы крови и клиническим контекстом.")

    for f in moderate:
        if f.include_in_summary:
            parts.append(f.summary_text)

    if not parts:
        parts.append("Обнаружены отклонения от референса; для интерпретации требуется очная оценка врача.")

    return " ".join(parts).strip()


def synthesize_risk(findings: List[Finding], values: List[LabValue], profile: str) -> Tuple[str, List[str], List[dict]]:
    """
    Продакшен-синтез: findings + values → (summary, hypotheses, next_steps).
    next_steps с ключами direction, what, why, priority (спека); check = what для legacy.
    """
    summary = build_summary(findings, values, profile)
    hypotheses = build_working_hypotheses(findings, profile)
    steps = build_next_steps(findings, profile)
    return summary, hypotheses, steps


def build_working_hypotheses(findings: List[Finding], profile: str) -> List[str]:
    """Рабочие гипотезы: липиды + углеводный блок при наличии fructosamine finding."""
    hypos: List[str] = []
    if profile == "lipid_panel":
        has_severe = any(f.code == "severe_hypercholesterolemia" for f in findings)
        has_ldl = any(f.code in ("marked_ldl_elevation", "elevated_ldl") for f in findings)
        if has_severe or has_ldl:
            hypos.append("Атерогенная дислипидемия")
            hypos.append("Возможна первичная/семейная гиперхолестеринемия")
        # Углеводный блок: при любом finding по фруктозамину
        fruct = any(
            f.code in ("fructosamine_elevated_with_normal_hba1c", "fructosamine_elevated")
            for f in findings
        )
        if fruct:
            hypos.append("Возможны ранние или нестойкие нарушения углеводного обмена")
    for f in findings:
        if f.include_in_hypotheses and f.title and f.title not in hypos:
            hypos.append(f.title)
    return hypos[:8]


def build_next_steps(findings: List[Finding], profile: str) -> List[dict]:
    """Конкретные next steps из findings; не только «идите к врачу»."""
    steps: List[dict] = []
    if profile == "lipid_panel":
        has_lipid_abnormal = any(
            f.code in ("severe_hypercholesterolemia", "marked_ldl_elevation", "elevated_ldl", "elevated_cholesterol")
            for f in findings
        )
        if has_lipid_abnormal:
            steps.append({"direction": "Липидный обмен", "what": "Повторная липидограмма натощак", "check": "Повторная липидограмма натощак", "why": "Подтверждение стойкости отклонений", "priority": "высокий"})
            steps.append({"direction": "Липидный обмен", "what": "ApoB / non-HDL-C", "check": "ApoB / non-HDL-C", "why": "Уточнение атерогенной нагрузки", "priority": "средний"})
            steps.append({"direction": "Эндокринология", "what": "ТТГ", "check": "ТТГ", "why": "Исключение вторичных причин дислипидемии", "priority": "средний"})
        # Углеводный блок: при любом finding по фруктозамину не терять глюкозу и HOMA-IR
        fruct = any(
            f.code in ("fructosamine_elevated_with_normal_hba1c", "fructosamine_elevated")
            for f in findings
        )
        if fruct:
            steps.append({"direction": "Углеводный обмен", "what": "Глюкоза натощак", "check": "Глюкоза натощак", "why": "Уточнение углеводного обмена", "priority": "средний"})
            steps.append({"direction": "Углеводный обмен", "what": "Инсулин / HOMA-IR по показаниям", "check": "Инсулин / HOMA-IR по показаниям", "why": "Оценка инсулинорезистентности", "priority": "средний"})
    if not steps:
        steps.append({"direction": "Общее", "what": "Очная клиническая интерпретация", "check": "Очная клиническая интерпретация", "why": "Оценка в контексте анамнеза", "priority": "средний"})
    return steps


def build_limitations(profile: str, has_findings: bool) -> List[str]:
    """Две короткие строки без пересечения смысла."""
    limits: List[str] = []
    limits.append("Интерпретация не заменяет очную оценку врача.")
    if profile == "lipid_panel" and has_findings:
        limits.append(
            "Для подтверждения причины дислипидемии нужна оценка сердечно-сосудистого риска и исключение вторичных причин; "
            "изолированный лабораторный отчёт не позволяет установить диагноз без клинического контекста."
        )
    else:
        limits.append("Результаты требуют клинической оценки в контексте анамнеза.")
    return limits


def build_group_interpretations(findings: List[Finding], values: List[LabValue], profile: str) -> List[dict]:
    """Групповая интерпретация по профилю. markers — технические коды; рендер подставляет human labels в pipeline."""
    groups: List[dict] = []
    if profile == "lipid_panel":
        lipid_f = [f for f in findings if f.group == "lipid"]
        if lipid_f:
            groups.append({
                "group": "Липидный обмен",
                "markers": list({m for f in lipid_f for m in f.supporting_markers}),
                "interpretation": "Выраженная атерогенная дислипидемия" if any(f.severity == "high" for f in lipid_f) else "Отклонения липидного профиля требуют оценки.",
            })
        glucose_f = [f for f in findings if f.group == "glucose"]
        hba1c_val = next((v for v in values if v.code == "hba1c"), None)
        fruct_val = next((v for v in values if v.code == "fructosamine"), None)
        if glucose_f or (hba1c_val and fruct_val):
            interp = "HbA1c в пределах референса, но фруктозамин повышен; требуется уточнение в динамике и сопоставление с глюкозой" if glucose_f else "HbA1c и фруктозамин в пределах референса."
            groups.append({"group": "Углеводный обмен", "markers": ["hba1c", "fructosamine"], "interpretation": interp})
        crp_val = next((v for v in values if v.code in ("hs_crp", "crp")), None)
        if crp_val:
            interp = "hs-CRP низкий, признаков выраженного воспалительного сигнала по этому маркеру нет" if (crp_val.value or 0) < 1 else f"С-реактивный белок {crp_val.value}."
            groups.append({"group": "Воспаление", "markers": [crp_val.code], "interpretation": interp})
    return groups
