"""
Единая структура пользовательского отчёта (GOLD STANDARD) для лабораторных документов.

Юридически безопасные формулировки: рабочие гипотезы, не диагноз; рекомендации — через врача.
Секции согласованы с SOAP / lab interpretation, но в доступном виде для пациента.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.unified_lab_report_presenter import (
    _dedup,
    _extract_follow_checks,
    _extract_group_names,
    _extract_hypotheses,
    _extract_summary_lines,
    _s,
    _safe_short,
)


LEGAL_DISCLAIMER_SHORT = (
    "Информация носит справочный характер, не является медицинским диагнозом и не заменяет очную консультацию врача."
)

REFINEMENT_GENERIC = (
    "Для более точной интерпретации желательны: полный текст бланка, даты взятия/выполнения, "
    "единый контекст жалоб и приёма лекарств/БАДов; при повторных анализах — сравнение с прошлыми результатами."
)


def _material_label_ru(physician_report: Dict[str, Any], document_type: str) -> str:
    raw = _s(physician_report.get("material"))
    mapping = {
        "multi_doc": "Несколько документов (сводный отчёт)",
        "blood": "Кровь (все доступные виды исследований крови)",
        "urine": "Моча",
        "stool": "Кал",
        "saliva": "Слюна",
        "swab": "Пробы со слизистых / мазки",
        "csf": "Ликвор",
        "semen": "Сперма",
        "tissue": "Ткань / биопсия",
        "serology": "Серология",
        "genetics": "Генетика",
        "unknown": "Лабораторный документ",
        "conflict": "Лабораторный документ (тип уточняется)",
    }
    if raw and raw in mapping:
        return mapping[raw]
    low = (document_type or "").lower()
    if "urinalysis" in low or "urine" in low:
        return "Моча"
    if "stool" in low or "fecal" in low or "кал" in low:
        return "Кал"
    if "saliva" in low or "слюн" in low:
        return "Слюна"
    if "skin" in low or "кож" in low:
        return "Пробы с кожи"
    if "cbc" in low or "biochemistry" in low or "lipid" in low or "blood" in low:
        return "Кровь (все доступные виды исследований крови)"
    return mapping.get("unknown", "Лабораторный документ")


def _list_from_field(report: Dict[str, Any], key: str, limit: int = 8) -> List[str]:
    val = report.get(key)
    if val is None:
        return []
    if isinstance(val, str) and val.strip():
        return _dedup([val.strip()], limit=limit)
    if isinstance(val, list):
        return _dedup([_s(x) for x in val if _s(x)], limit=limit)
    return []


def _abnormal_brief_lines(report: Dict[str, Any], limit: int = 8) -> List[str]:
    rows = report.get("abnormal_markers_table") or report.get("abnormal_findings") or []
    out: List[str] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        name = _s(row.get("name") or row.get("marker"))
        val = _s(row.get("value"))
        flag = _s(row.get("flag") or row.get("direction"))
        if not name and not val:
            continue
        line = f"{name} {val}".strip()
        if flag:
            line += f" ({flag})"
        if line:
            out.append(line)
    return _dedup(out, limit=limit)


def _grouped_interpretation_brief(report: Dict[str, Any], limit: int = 6) -> List[str]:
    rows = report.get("grouped_interpretation_table") or []
    out: List[str] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        g = _s(row.get("group"))
        interp = _s(row.get("interpretation"))
        if g and interp:
            out.append(f"{g}: {interp}")
        elif interp:
            out.append(interp)
    return _dedup(out, limit=limit)


def build_gold_standard_bundle(
    *,
    physician_report: Dict[str, Any],
    document_type: str,
    filename: str,
    display_summary: str,
    follow_checks: Optional[List[str]] = None,
    hypotheses: Optional[List[str]] = None,
    safe_next_steps: str = "",
    when_urgent: str = "",
    case_summary: str = "",
) -> Dict[str, Any]:
    """
    Возвращает словарь для user_report_structured['gold_standard'].
    Все списки — короткие строки на русском, без назначений от имени врача.
    """
    pr = physician_report if isinstance(physician_report, dict) else {}
    follow_checks = follow_checks if follow_checks is not None else _extract_follow_checks(pr)
    hypos = hypotheses if hypotheses is not None else _extract_hypotheses(pr)
    summary_lines = _extract_summary_lines(pr)
    groups = _extract_group_names(pr)

    material_label = _material_label_ru(pr, document_type)

    brief = _safe_short(_s(display_summary), 280) or (
        summary_lines[0] if summary_lines else f"Документ «{_s(filename) or 'анализ'}» загружен для справочной оценки."
    )

    objective_parts: List[str] = []
    objective_parts.extend(summary_lines[:3])
    abnormal_lines = _abnormal_brief_lines(pr)
    if abnormal_lines:
        objective_parts.append("Отмеченные в бланке показатели (кратко): " + "; ".join(abnormal_lines[:5]) + ".")
    gi = _grouped_interpretation_brief(pr)
    objective_parts.extend(gi[:4])
    if groups:
        objective_parts.append("Зоны внимания по группам: " + ", ".join(groups[:5]) + ".")
    objective = _dedup([_safe_short(x, 320) for x in objective_parts if _s(x)], limit=8)
    if not objective:
        objective = [
            "По загруженному тексту извлечены показатели; детали см. в оригинале бланка и у лечащего врача."
        ]

    interpretation: List[str] = []
    interpretation.append(
        "Ниже — ориентировочное объяснение простым языком. Окончательное значение имеют жалобы, осмотр и клинический контекст."
    )
    if case_summary:
        interpretation.append(_safe_short(case_summary, 400))
    elif summary_lines:
        for line in summary_lines[1:4]:
            if line not in interpretation:
                interpretation.append(_safe_short(line, 320))

    hypo_block: List[str] = []
    for h in hypos[:6]:
        hypo_block.append(f"Возможное направление оценки (рабочая гипотеза, не диагноз): {h}")
    if not hypo_block:
        hypo_block.append(
            "Явных паттернов «под конкретный диагноз» по одному бланку без жалоб обычно не ставят — нужна очная оценка."
        )

    risks: List[str] = [
        "Риски для здоровья оцениваются только вместе с самочувствием, динамикой и очным осмотром.",
    ]
    if abnormal_lines:
        risks.append("Наличие отклонений в бланке повышает приоритет обсуждения с врачом, но само по себе не означает тяжёлое заболевание без контекста.")

    refinement: List[str] = [REFINEMENT_GENERIC]
    if follow_checks:
        refinement.append("Для уточнения плана часто полезно: " + "; ".join(follow_checks[:5]) + ".")

    plan_now: List[str] = []
    plan_later: List[str] = []
    if _s(safe_next_steps):
        plan_now.append(_safe_short(safe_next_steps, 400))
    else:
        plan_now.append("Показать бланк лечащему врачу и согласовать план наблюдения или дообследования.")
    plan_later.append("При необходимости — повторные анализы и сравнение в динамике по рекомендации врача.")

    tests = _dedup(follow_checks, limit=10)
    if not tests:
        tests = ["Уточнить у врача, какие контрольные анализы уместны в вашей ситуации."]

    nutrition = _list_from_field(pr, "nutrition", limit=8)
    if not nutrition:
        nutrition = [
            "Сбалансированный рацион без крайних ограничений; детали — с врачом/нутрициологом при наличии показаний.",
        ]

    supplements = _list_from_field(pr, "medications", limit=6)
    supp_alt = _list_from_field(pr, "alternative_treatment", limit=4)
    supplements.extend(supp_alt)
    supplements = _dedup(supplements, limit=10)
    if not supplements:
        supplements = [
            "БАДы и витамины не назначаются по одному бланку без очной оценки; обсудите возможные варианты с врачом.",
        ]
    else:
        supplements = ["Обсудить с врачом до приёма: " + x for x in supplements[:8]]

    activity = _list_from_field(pr, "physical_exercises", limit=8) or _list_from_field(pr, "activity", limit=8)
    if not activity:
        activity = [
            "Умеренная активность по самочувствию; резкие нагрузки без рекомендации врача не обязательны.",
        ]

    treatment = _list_from_field(pr, "treatment_plan", limit=8) + _list_from_field(pr, "treatment", limit=6)
    treatment = _dedup(treatment, limit=10)
    if not treatment:
        treatment = [
            "Схемы лечения назначает врач; по анализу можно лишь наметить направления для обсуждения.",
        ]
    else:
        treatment = ["Возможные направления для обсуждения с врачом: " + x for x in treatment[:8]]

    avoid: List[str] = [
        "Не менять назначенное лечение и не отменять препараты без врача.",
        "Не полагаться только на интерпретацию ИИ при ухудшении самочувствия.",
    ]
    lim = pr.get("limitations")
    if isinstance(lim, list):
        avoid.extend(_dedup([_s(x) for x in lim[:4]], limit=6))

    urgent = _s(when_urgent) or (
        "Срочно обращаться при резком ухудшении, сильной боли, высокой температуре, кровотечении, нарушении сознания."
    )

    sections: List[Dict[str, Any]] = [
        {"id": "brief_summary", "title": "Краткий вывод", "variant": "emphasis", "items": [brief]},
        {
            "id": "material_context",
            "title": "Группа / биоматериал",
            "variant": "neutral",
            "items": [f"Отчёт относится к: {material_label}. Файл: {_s(filename) or '—'}."],
        },
        {"id": "objective_facts", "title": "Что видно по данным (объективно)", "variant": "neutral", "items": objective},
        {"id": "interpretation_plain", "title": "Интерпретация простым языком", "variant": "neutral", "items": interpretation},
        {"id": "hypotheses", "title": "Рабочие гипотезы (не диагноз)", "variant": "warning", "items": hypo_block},
        {"id": "risks", "title": "Риски и осторожность", "variant": "neutral", "items": risks},
        {"id": "refinement", "title": "Что добавить для уточнённого отчёта", "variant": "neutral", "items": refinement},
        {
            "id": "plan",
            "title": "Что делать: приоритеты",
            "variant": "emphasis",
            "items": [
                "Приоритет сейчас: " + plan_now[0],
            ]
            + (["Далее: " + plan_later[0]] if plan_later else []),
        },
        {"id": "tests_to_confirm", "title": "Что проверить / дообследование", "variant": "neutral", "items": tests},
        {"id": "nutrition", "title": "Питание (ориентиры)", "variant": "neutral", "items": nutrition},
        {"id": "supplements", "title": "Витамины и БАДы", "variant": "warning", "items": supplements},
        {"id": "activity", "title": "Физическая активность", "variant": "neutral", "items": activity},
        {"id": "treatment_alternatives", "title": "Возможные направления терапии / альтернативы", "variant": "neutral", "items": treatment},
        {"id": "avoid", "title": "Чего не делать", "variant": "warning", "items": avoid},
        {"id": "when_urgent", "title": "Когда срочно к врачу", "variant": "danger", "items": [_safe_short(urgent, 450)]},
        {"id": "disclaimer", "title": "Юридическая оговорка", "variant": "legal", "items": [LEGAL_DISCLAIMER_SHORT]},
    ]

    # AI Diagnostic Brain (дополнительный сценарный слой) — без замены базовой клинической логики.
    try:
        from app.services.ai_diagnostic_brain import (
            autolink_knowledge,
            build_full_report,
            derive_lab_flags,
            match_scenarios,
        )

        flags = derive_lab_flags(pr)
        matched = match_scenarios(flags)
        k_auto = autolink_knowledge(
            {
                "report_type": "lab",
                "group": material_label,
                "lab_flags": flags,
                "lab_markers": pr.get("abnormal_markers_table") or [],
                "symptoms": [],
                "profile": {},
                "current_hypotheses": [],
            }
        )
        brain = build_full_report(matched, knowledge_autolink=k_auto)
        if matched:
            sections.append(
                {
                    "id": "ai_brain_summary",
                    "title": "Сценарный клинический слой (AI Diagnostic Brain)",
                    "variant": "neutral",
                    "items": [
                        "Сработали сценарии: " + ", ".join([str(x.get("scenario_id") or "") for x in matched if str(x.get("scenario_id") or "").strip()][:10]),
                        "Флаги: " + ", ".join(flags[:15]) if flags else "Флаги: не определены",
                    ],
                }
            )
        k_sources = _dedup([_s(x) for x in (k_auto.get("knowledge_sources") or []) if _s(x)], limit=12)
        if k_sources:
            sections.append(
                {
                    "id": "brain_knowledge_sources",
                    "title": "Подключённые справочники (knowledge autolink)",
                    "variant": "neutral",
                    "items": ["Использованы источники: " + ", ".join(k_sources)],
                }
            )
        k_topics = _dedup([_s(x) for x in (k_auto.get("knowledge_topics") or []) if _s(x)], limit=14)
        if k_topics:
            sections.append(
                {
                    "id": "brain_knowledge_topics",
                    "title": "Ключевые клинические темы случая",
                    "variant": "neutral",
                    "items": k_topics,
                }
            )

        brain_auto = k_auto.get("brain_enhance") if isinstance(k_auto.get("brain_enhance"), dict) else {}
        merged_what_to_add = _dedup(
            [_s(x) for x in (brain.get("what_to_add") or []) if _s(x)]
            + [_s(x) for x in (brain_auto.get("what_to_add") or []) if _s(x)],
            limit=12,
        )
        if merged_what_to_add:
            sections.append(
                {
                    "id": "brain_what_to_add",
                    "title": "Что добавить для уточнения (сценарный слой)",
                    "variant": "neutral",
                    "items": merged_what_to_add,
                }
            )
        if brain.get("plan"):
            p = brain.get("plan") or {}
            plan_lines = []
            plan_lines.extend(["Приоритет 1: " + _s(x) for x in (p.get("priority_1") or []) if _s(x)])
            plan_lines.extend(["Приоритет 2: " + _s(x) for x in (p.get("priority_2") or []) if _s(x)])
            plan_lines.extend(["Проверить: " + _s(x) for x in (p.get("tests") or []) if _s(x)])
            if plan_lines:
                sections.append(
                    {
                        "id": "brain_plan",
                        "title": "План по сценариям",
                        "variant": "emphasis",
                        "items": _dedup(plan_lines, limit=14),
                    }
                )
        auto_nutrition = _dedup([_s(x) for x in (brain_auto.get("nutrition") or []) if _s(x)], limit=8)
        if auto_nutrition:
            sections.append(
                {
                    "id": "brain_nutrition_autolink",
                    "title": "Питание (knowledge autolink)",
                    "variant": "neutral",
                    "items": auto_nutrition,
                }
            )
        auto_red_flags = _dedup([_s(x) for x in (brain_auto.get("red_flags") or []) if _s(x)], limit=8)
        if auto_red_flags:
            sections.append(
                {
                    "id": "brain_red_flags_autolink",
                    "title": "Красные флаги (knowledge autolink)",
                    "variant": "danger",
                    "items": auto_red_flags,
                }
            )
    except Exception:
        pass

    return {
        "version": 1,
        "material_label_ru": material_label,
        "document_type": document_type,
        "sections": sections,
    }


def merge_gold_into_user_structured(user_report_structured: Dict[str, Any], gold: Dict[str, Any]) -> Dict[str, Any]:
    """Добавляет gold_standard к существующей структуре, не удаляя legacy blocks."""
    out = dict(user_report_structured) if user_report_structured else {}
    out["gold_standard"] = gold
    return out


def build_gold_standard_for_aggregate(report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Сводный отчёт по нескольким документам: те же секции, данные из агрегированного API-ответа.
    """
    aggregate = report.get("aggregate_clinical") if isinstance(report.get("aggregate_clinical"), dict) else {}
    main_block = aggregate.get("main_conclusion") if isinstance(aggregate.get("main_conclusion"), dict) else {}
    summary_lines: List[str] = []
    if _s(main_block.get("main_priority")):
        summary_lines.append("Основной приоритет: " + _s(main_block.get("main_priority")))
    summary_lines.extend([str(x) for x in (main_block.get("secondary_findings") or []) if str(x).strip()][:2])
    if not summary_lines:
        summary_lines = [str(x) for x in (report.get("conclusions") or []) if str(x).strip()][:6]

    pr: Dict[str, Any] = {
        "summary": summary_lines[:6],
        "top_hypotheses_table": [{"hypothesis": str(h)} for h in (report.get("hypotheses") or []) if str(h).strip()][:8],
        "recommended_followup_table": [{"check": str(x)} for x in (report.get("diagnostics") or []) if str(x).strip()][:10],
        "grouped_interpretation_table": [],
        "abnormal_markers_table": [],
        "material": "multi_doc",
    }
    matrix = aggregate.get("document_matrix") if isinstance(aggregate.get("document_matrix"), list) else []
    if matrix:
        for i, row in enumerate(matrix):
            if not isinstance(row, dict):
                continue
            pr["grouped_interpretation_table"].append(
                {
                    "group": str(row.get("document") or f"Анализ {i+1}"),
                    "interpretation": str(row.get("main_conclusion") or "")[:800],
                }
            )
    else:
        for i, sec in enumerate(report.get("aggregate_document_sections") or []):
            if not isinstance(sec, dict):
                continue
            pr["grouped_interpretation_table"].append(
                {
                    "group": str(sec.get("analysis_type_label_ru") or sec.get("filename") or f"Анализ {i+1}"),
                    "interpretation": str(sec.get("short_summary") or "")[:800],
                }
            )
    return build_gold_standard_bundle(
        physician_report=pr,
        document_type=str(report.get("document_type") or "aggregate_clinical_report"),
        filename=str(report.get("document_name") or "Сводный отчёт"),
        display_summary=str(report.get("display_summary") or report.get("user_summary") or ""),
        follow_checks=_extract_follow_checks(pr),
        hypotheses=_extract_hypotheses(pr),
        safe_next_steps=str(report.get("safe_next_steps") or ""),
        when_urgent=str(report.get("when_urgent") or ""),
        case_summary=str(report.get("case_summary") or ""),
    )
