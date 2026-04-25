"""
Движок общего анализа мочи (ОАМ): извлечение значений, правила интерпретации, отчёт для врача.
Не путать с organic_acids_urine. Профиль: urinalysis.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Коды маркеров ОАМ
URINE_PH = "urine_ph"
URINE_SPECIFIC_GRAVITY = "urine_specific_gravity"
URINE_PROTEIN = "urine_protein"
URINE_GLUCOSE = "urine_glucose"
URINE_KETONES = "urine_ketones"
URINE_BLOOD = "urine_blood"
URINE_NITRITES = "urine_nitrites"
URINE_LEUKOCYTES = "urine_leukocytes"
URINE_ERYTHROCYTES = "urine_erythrocytes"
URINE_BACTERIA = "urine_bacteria"
URINE_BILIRUBIN = "urine_bilirubin"
URINE_UROBILINOGEN = "urine_urobilinogen"

# Ключевые фразы для извлечения (нижний регистр)
_URINE_PATTERNS = [
    (URINE_PH, r"ph\s*[:\s]*(\d+[,.]?\d*)", "numeric"),
    (URINE_SPECIFIC_GRAVITY, r"(?:относительная\s+плотность|плотность|specific\s+gravity)\s*[:\s]*(\d+[,.]?\d*)", "numeric"),
    (URINE_PROTEIN, r"белок\s*(?:в\s+моче)?\s*[:\s]*(отрицательно|положительно|trace|\d+[,.]?\d*)", "qual"),
    (URINE_GLUCOSE, r"глюкоза\s*[:\s]*(отрицательно|положительно|trace|\d+[,.]?\d*)", "qual"),
    (URINE_KETONES, r"кетоны\s*[:\s]*(отрицательно|положительно|trace|\d+[,.]?\d*)", "qual"),
    (URINE_BLOOD, r"реакция\s+на\s+кровь\s*[:\s]*(\d+[,.]?\d*|отрицательно|положительно)", "blood"),
    (URINE_NITRITES, r"нитриты\s*[:\s]*(отрицательно|положительно)", "qual"),
    (URINE_LEUKOCYTES, r"лейкоциты\s*[:\s]*(отрицательно|положительно|<?\s*\d+[,.]?\d*)", "qual"),
    (URINE_ERYTHROCYTES, r"эритроциты\s*[:\s]*(отрицательно|положительно|<?\s*\d+[,.]?\d*)", "qual"),
    (URINE_BACTERIA, r"бактерии\s*[:\s]*(не\s+обнаружено|обнаружено|отрицательно|положительно)", "qual"),
]


def _parse_number(s: str) -> Optional[float]:
    if not s:
        return None
    s = s.replace(",", ".").strip()
    try:
        return float(s)
    except ValueError:
        return None


def extract_urine_values(text: str) -> Dict[str, Dict[str, Any]]:
    """
    Извлекает показатели ОАМ из текста. Возвращает dict: code -> {value, value_text, ref_high, ref_low, status}.
    """
    if not (text or "").strip():
        return {}
    low = text.lower().strip()
    out: Dict[str, Dict[str, Any]] = {}

    # pH
    m = re.search(r"ph\s*[:\s]*(\d+[,.]?\d*)", low, re.I)
    if m:
        v = _parse_number(m.group(1))
        if v is not None:
            out[URINE_PH] = {"value": v, "value_text": str(v), "ref_low": 4.5, "ref_high": 8.0, "status": "normal" if 4.5 <= v <= 8 else "high" if v > 8 else "low"}

    # Относительная плотность
    m = re.search(r"(?:относительная\s+плотность|плотность)\s*[:\s]*(\d{4})", low)
    if m:
        v = _parse_number(m.group(1))
        if v is not None:
            out[URINE_SPECIFIC_GRAVITY] = {"value": v, "value_text": str(int(v)), "ref_low": 1010, "ref_high": 1025, "status": "normal" if 1010 <= v <= 1025 else "low" if v < 1010 else "high"}

    # Белок
    if "белок" in low and ("отрицательно" in low or "отриц" in low):
        out[URINE_PROTEIN] = {"value": None, "value_text": "отрицательно", "status": "normal"}
    elif re.search(r"белок\s*[:\s]*положительно", low):
        out[URINE_PROTEIN] = {"value": None, "value_text": "положительно", "status": "high"}

    # Глюкоза
    if "глюкоза" in low and "отрицательно" in low:
        out[URINE_GLUCOSE] = {"value": None, "value_text": "отрицательно", "status": "normal"}
    elif re.search(r"глюкоза\s*[:\s]*положительно", low):
        out[URINE_GLUCOSE] = {"value": None, "value_text": "положительно", "status": "high"}

    # Кетоны
    if "кетоны" in low and "отрицательно" in low:
        out[URINE_KETONES] = {"value": None, "value_text": "отрицательно", "status": "normal"}

    # Реакция на кровь
    m = re.search(r"реакция\s+на\s+кровь\s*[:\s]*(\d+[,.]?\d*)", low)
    if m:
        v = _parse_number(m.group(1))
        if v is not None:
            out[URINE_BLOOD] = {"value": v, "value_text": str(v), "ref_high": 0, "status": "high" if v > 0 else "normal"}
    elif "реакция на кровь" in low and "отрицательно" in low:
        out[URINE_BLOOD] = {"value": 0, "value_text": "отрицательно", "status": "normal"}

    # Нитриты
    if "нитриты" in low:
        out[URINE_NITRITES] = {"value": None, "value_text": "положительно" if "положительно" in low else "отрицательно", "status": "high" if "положительно" in low else "normal"}

    # Лейкоциты
    if "лейкоцит" in low:
        out[URINE_LEUKOCYTES] = {"value": None, "value_text": "положительно" if "положительно" in low and "отрицательно" not in low else "отрицательно", "status": "high" if "положительно" in low and "отрицательно" not in low else "normal"}

    # Эритроциты
    if "эритроцит" in low:
        out[URINE_ERYTHROCYTES] = {"value": None, "value_text": "положительно" if "положительно" in low and "отрицательно" not in low else "отрицательно", "status": "high" if "положительно" in low and "отрицательно" not in low else "normal"}

    # Бактерии
    if "бактерии" in low:
        out[URINE_BACTERIA] = {"value": None, "value_text": "обнаружено" if "обнаружено" in low and "не обнаружено" not in low else "не обнаружено", "status": "high" if "обнаружено" in low and "не обнаружено" not in low else "normal"}

    return out


def _interpret_urinalysis(values: Dict[str, Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]], List[str], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Правила интерпретации ОАМ. Возвращает (summary, abnormal_findings, hypotheses, next_steps, grouped_interpretation, risk_assessment).
    """
    summary_parts: List[str] = []
    abnormal: List[Dict[str, Any]] = []
    hypotheses: List[str] = []
    next_steps: List[Dict[str, Any]] = []
    grouped: List[Dict[str, Any]] = []

    blood = values.get(URINE_BLOOD, {})
    protein = values.get(URINE_PROTEIN, {})
    nitrites = values.get(URINE_NITRITES, {})
    leukocytes = values.get(URINE_LEUKOCYTES, {})
    bacteria = values.get(URINE_BACTERIA, {})
    erythrocytes = values.get(URINE_ERYTHROCYTES, {})
    glucose = values.get(URINE_GLUCOSE, {})
    ketones = values.get(URINE_KETONES, {})
    sg = values.get(URINE_SPECIFIC_GRAVITY, {})

    # Infection pattern
    nit_pos = nitrites.get("status") == "high" or (nitrites.get("value_text") or "").lower() == "положительно"
    leu_pos = leukocytes.get("status") == "high"
    bac_pos = bacteria.get("status") == "high"
    has_infection = nit_pos or leu_pos or bac_pos
    if not has_infection:
        grouped.append({
            "group": "Мочевой осадок (лейкоциты, бактерии, нитриты)",
            "markers": ["urine_leukocytes", "urine_bacteria", "urine_nitrites"],
            "interpretation": "Признаков воспалительного процесса не выявлено.",
        })
        summary_parts.append("Признаков воспалительного процесса в мочевых путях не выявлено: лейкоциты и нитриты отрицательные, бактерии не обнаружены.")
    else:
        grouped.append({
            "group": "Мочевой осадок (лейкоциты, бактерии, нитриты)",
            "markers": ["urine_leukocytes", "urine_bacteria", "urine_nitrites"],
            "interpretation": "Обнаружены признаки возможного воспаления/инфекции мочевых путей.",
        })
        summary_parts.append("Обнаружены признаки возможного воспаления/инфекции мочевых путей (лейкоциты, нитриты или бактерии).")
        abnormal.append({"marker": "Инфекционный паттерн", "value": "поддерживается", "direction": "high", "comment": "Требуется клиническая оценка."})
        next_steps.append({"direction": "Мочевые пути", "check": "Очная оценка врача при симптомах ИМП", "why": "Исключение инфекции", "priority": "высокий"})

    # Proteinuria
    protein_pos = protein.get("status") == "high"
    if not protein_pos:
        grouped.append({
            "group": "Белок",
            "markers": ["urine_protein"],
            "interpretation": "Протеинурия не выявлена.",
        })
    else:
        grouped.append({
            "group": "Белок",
            "markers": ["urine_protein"],
            "interpretation": "Обнаружен белок в моче; требуется оценка.",
        })
        summary_parts.append("Обнаружен белок в моче; требуется оценка.")
        abnormal.append({"marker": "Белок в моче", "value": protein.get("value_text", ""), "direction": "high", "comment": "Требуется клиническая оценка."})

    # Glycosuria / ketonuria
    glucose_pos = glucose.get("status") == "high"
    ketones_pos = ketones.get("status") == "high"
    if not glucose_pos and not ketones_pos:
        grouped.append({
            "group": "Глюкоза и кетоны",
            "markers": ["urine_glucose", "urine_ketones"],
            "interpretation": "Глюкозурия и кетонурия не выявлены.",
        })
    else:
        interp_parts = []
        if glucose_pos:
            interp_parts.append("глюкозурия")
            abnormal.append({"marker": "Глюкоза в моче", "value": glucose.get("value_text", ""), "direction": "high", "comment": "Требуется оценка углеводного обмена."})
        if ketones_pos:
            interp_parts.append("кетонурия")
        grouped.append({
            "group": "Глюкоза и кетоны",
            "markers": ["urine_glucose", "urine_ketones"],
            "interpretation": f"Обнаружена {' и '.join(interp_parts)}; требуется оценка.",
        })

    # Hematuria / reaction on blood
    blood_val = blood.get("value")
    blood_status = blood.get("status")
    eryth_status = erythrocytes.get("status")
    eryth_pos = eryth_status == "high"
    has_blood_signal = blood_status == "high" or (blood_val is not None and blood_val > 0)
    
    if not has_blood_signal and not eryth_pos:
        grouped.append({
            "group": "Кровь/эритроциты",
            "markers": ["urine_blood", "urine_erythrocytes"],
            "interpretation": "Явной гематурии по количеству эритроцитов нет; реакция на кровь отрицательная.",
        })
    elif has_blood_signal and not eryth_pos:
        grouped.append({
            "group": "Кровь/эритроциты",
            "markers": ["urine_blood", "urine_erythrocytes"],
            "interpretation": "Явной гематурии по количеству эритроцитов нет; отмечается слабоположительная реакция на кровь.",
        })
        if blood_val == 0.3:
            summary_parts.append("Отмечается изолированная слабоположительная реакция на кровь без подтверждения по эритроцитам; требует оценки только при наличии клинических симптомов или при повторном выявлении.")
        else:
            summary_parts.append("Отмечается изолированная слабоположительная реакция на кровь без подтверждения по эритроцитам; требует оценки в клиническом контексте.")
        abnormal.append({
            "marker": "Реакция на кровь",
            "value": str(blood.get("value_text") or blood_val),
            "ref_high": "отрицательно",
            "direction": "high",
            "comment": "Мягкое отклонение, подлежит клинической оценке.",
        })
        next_steps.append({"direction": "Мочевые пути", "check": "При стойкой положительной реакции на кровь — контрольный ОАМ и дальнейшее уточнение по клинике", "why": "Контроль изолированного сигнала", "priority": "средний"})
    else:
        grouped.append({
            "group": "Кровь/эритроциты",
            "markers": ["urine_blood", "urine_erythrocytes"],
            "interpretation": "Обнаружена реакция на кровь и эритроциты в осадке; требуется клиническая оценка.",
        })
        summary_parts.append("Обнаружена реакция на кровь и эритроциты в осадке; требуется клиническая оценка.")
        abnormal.append({"marker": "Реакция на кровь / эритроциты", "value": str(blood.get("value_text") or ""), "direction": "high", "comment": "Требуется оценка гематурии."})

    # Specific gravity low
    sg_val = sg.get("value")
    if sg_val is not None and sg_val < 1010:
        abnormal.append({
            "marker": "Относительная плотность",
            "value": str(int(sg_val)),
            "ref_low": "1010",
            "ref_high": "1025",
            "direction": "low",
            "comment": "Снижение относительной плотности; чаще отражает разбавленную мочу и без клинического контекста самостоятельной диагностической ценности не имеет.",
        })
        if "плотность" not in " ".join(summary_parts).lower():
            summary_parts.append("Относительная плотность несколько снижена и может отражать разбавленную мочу.")

    # Hypotheses
    if not has_infection and not protein_pos and not has_blood_signal:
        hypotheses.append("Убедительных лабораторных паттернов за инфекцию мочевых путей, протеинурию или выраженную гематурию не выявлено.")
    elif has_blood_signal and not eryth_pos:
        hypotheses.append("Отмечается изолированный мягкий сигнал по реакции на кровь без подтверждения по эритроцитам; требует оценки в клиническом контексте.")
    if not has_infection:
        hypotheses.append("Данных за инфекцию мочевых путей по анализу не получено.")
    if not protein_pos:
        hypotheses.append("Протеинурия не выявлена.")
    if has_blood_signal and not eryth_pos:
        hypotheses.append("Выраженной гематурии по количеству эритроцитов нет.")

    # Итоговый summary
    if not summary_parts:
        summary_parts.append("Общий анализ мочи в целом без значимых патологических изменений.")
    else:
        full = "Общий анализ мочи в целом без значимых патологических изменений. " + " ".join(summary_parts)
        summary_parts = [full.strip()]

    # Next steps: сначала специфичные по находкам, затем базовые
    default_steps = [
        {"direction": "Общее", "check": "Повтор ОАМ при жалобах или в динамике", "why": "Контроль при необходимости", "priority": "средний"},
        {"direction": "Мочевые пути", "check": "При симптомах со стороны мочевых путей — очная оценка врача", "why": "Клиническая оценка", "priority": "средний"},
    ]
    next_steps = next_steps + default_steps

    # Risk assessment
    risk_level = "low"
    if has_infection or (has_blood_signal and eryth_pos) or protein_pos:
        risk_level = "moderate"
    
    risk_assessment = {
        "overall_level": risk_level,
        "overall_score": 0.3 if risk_level == "moderate" else 0.1,
        "primary_domain": "urinary",
        "domain_risks": [{
            "domain": "urinary",
            "level": risk_level,
            "score": 0.3 if risk_level == "moderate" else 0.1,
            "label": "Урологический риск",
            "rationale": [
                "Признаков инфекционного процесса или выраженных патологических изменений не выявлено." if not has_infection and not protein_pos and not (has_blood_signal and eryth_pos) else "Обнаружены признаки, требующие клинической оценки.",
            ],
            "drivers": [],
            "recommended_actions": [],
        }],
        "summary_text": "Низкий риск клинически значимых нарушений по данным анализа мочи. Признаков инфекционного процесса или выраженных патологических изменений не выявлено. Отмечается изолированный слабый сигнал по реакции на кровь, который требует оценки только при наличии жалоб или в динамике." if has_blood_signal and not eryth_pos and not has_infection and not protein_pos else "Низкий риск клинически значимых нарушений по данным анализа мочи. Признаков инфекционного процесса или выраженных патологических изменений не выявлено." if not has_infection and not protein_pos and not (has_blood_signal and eryth_pos) else "Умеренный риск клинически значимых нарушений по данным анализа мочи. Требуется клиническая оценка выявленных изменений.",
        "urgency": "non_urgent",
    }

    return summary_parts[0] if summary_parts else "Общий анализ мочи требует клинической интерпретации.", abnormal, hypotheses, next_steps, grouped, risk_assessment


def build_urinalysis_report(extracted_text: str, filename: str = "") -> Dict[str, Any]:
    """
    Строит physician report для ОАМ. Не использует CBC; заголовок и формулировки только для мочи.
    Унифицирован с другими профилями: grouped_interpretation_table, risk_assessment, hypotheses.
    """
    values = extract_urine_values(extracted_text)
    summary, abnormal, hypotheses, next_steps, grouped, risk_assessment = _interpret_urinalysis(values)

    title = "Структурированная интерпретация общего анализа мочи"
    report_title = "Отчёт для врача"
    report_subtitle = title

    professional_parts = [
        report_title,
        title,
        "",
        "Краткий вывод",
        summary,
        "",
    ]

    # Risk assessment
    if risk_assessment and risk_assessment.get("summary_text"):
        professional_parts.append("Оценка риска")
        professional_parts.append(risk_assessment.get("summary_text", ""))
        primary_domain = risk_assessment.get("primary_domain")
        domain_risks = risk_assessment.get("domain_risks") or []
        primary = next((d for d in domain_risks if d.get("domain") == primary_domain), None)
        if primary and primary.get("rationale"):
            for r in primary.get("rationale", [])[:3]:
                if r:
                    professional_parts.append(f"- {r}")
        professional_parts.append("")

    professional_parts.append("Ключевые отклонения")
    if abnormal:
        for a in abnormal:
            marker = a.get("marker", "—")
            value = a.get("value", "—")
            comment = a.get("comment", "")
            professional_parts.append(f"- {marker}: {value} {comment}")
    else:
        professional_parts.append("- Существенных отклонений не выявлено.")
    professional_parts.append("")

    # Grouped interpretation
    professional_parts.append("Клиническая интерпретация по группам")
    if grouped:
        for g in grouped:
            group_name = g.get("group", "—")
            markers = ", ".join(g.get("markers", [])) or "—"
            interp = g.get("interpretation", "—")
            professional_parts.append(f"- {group_name}: {interp}")
    else:
        professional_parts.append("- Нет групп для интерпретации.")
    professional_parts.append("")

    # Hypotheses
    if hypotheses:
        professional_parts.append("Рабочие гипотезы")
        for h in hypotheses[:5]:
            professional_parts.append(f"- {h}")
        professional_parts.append("")

    professional_parts.append("Что проверить дальше")
    for s in next_steps:
        professional_parts.append(f"- {s.get('check', '—')} ({s.get('why', '')})")
    professional_parts.append("")
    professional_parts.append("Ограничения интерпретации")
    professional_parts.append("- Интерпретация не заменяет очную оценку врача.")
    professional_parts.append("- Изолированный лабораторный результат требует сопоставления с жалобами и клиникой.")

    return {
        "doc_type": "urinalysis",
        "document_type": "urinalysis",
        "document_name": filename,
        "document_summary": {},
        "patient": {},
        "report_title": report_title,
        "report_subtitle": report_subtitle,
        "summary": [summary],
        "abnormal_findings": abnormal,
        "abnormal_markers_table": abnormal,
        "recommended_followup_table": [{"direction": s.get("direction", ""), "check": s.get("check", ""), "why": s.get("why", ""), "priority": s.get("priority", "")} for s in next_steps],
        "top_hypotheses_table": [{"hypothesis": h, "basis": "", "comment": ""} for h in hypotheses],
        "grouped_interpretation_table": grouped,
        "interpretation": [summary],
        "follow_up": {"tests": [s.get("check", "") for s in next_steps], "referrals": [], "notes": []},
        "limitations": ["Интерпретация не заменяет очную оценку врача.", "Изолированный лабораторный результат требует сопоставления с жалобами и клиникой."],
        "recommendation_blocks": [],
        "professional_summary": "\n".join(professional_parts),
        "risk_assessment": risk_assessment,
    }
