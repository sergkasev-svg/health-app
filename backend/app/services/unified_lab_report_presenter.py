from __future__ import annotations

from typing import Any, Dict, List


def _s(x: Any) -> str:
    return str(x or "").strip()


def _dedup(items: List[str], limit: int = 999) -> List[str]:
    out: List[str] = []
    seen = set()
    for x in items or []:
        s = _s(x)
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _sentences(items: List[str], limit: int = 4) -> str:
    clean = _dedup(items, limit=limit)
    if not clean:
        return ""
    out: List[str] = []
    for x in clean:
        out.append(x if x.endswith((".", "!", "?")) else (x + "."))
    return " ".join(out).strip()


def _safe_short(text: str, max_len: int = 420) -> str:
    s = _s(text)
    if len(s) <= max_len:
        return s
    cut = s[:max_len].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(",;:- ") + "…"


def _extract_follow_checks(report: Dict[str, Any]) -> List[str]:
    rows = report.get("recommended_followup_table") or []
    return _dedup([_s(x.get("check")) for x in rows if _s(x.get("check"))], limit=8)


def _extract_group_names(report: Dict[str, Any]) -> List[str]:
    rows = report.get("grouped_interpretation_table") or []
    names: List[str] = []
    for row in rows:
        val = _s(row.get("group") or row.get("label") or row.get("domain_key"))
        if val:
            names.append(val)
    return _dedup(names, limit=6)


def _extract_summary_lines(report: Dict[str, Any]) -> List[str]:
    return _dedup([_s(x) for x in (report.get("summary") or [])], limit=6)


def _extract_hypotheses(report: Dict[str, Any]) -> List[str]:
    rows = report.get("top_hypotheses_table") or []
    out: List[str] = []
    for row in rows:
        if isinstance(row, dict):
            val = _s(row.get("hypothesis"))
            if val:
                out.append(val)
        else:
            val = _s(row)
            if val:
                out.append(val)
    return _dedup(out, limit=5)


def _labels_from_brain_hypotheses(rows: List[Any]) -> List[str]:
    out: List[str] = []
    for row in rows or []:
        if isinstance(row, dict):
            lbl = _s(row.get("label") or row.get("hypothesis") or row.get("id"))
            if lbl:
                out.append(lbl)
        else:
            txt = _s(row)
            if txt:
                out.append(txt)
    return _dedup(out, limit=8)


def _extract_patient_type(report: Dict[str, Any]) -> str:
    profile = report.get("patient_type_profile") or {}
    return _s(profile.get("profile_title"))


def _default_when_urgent(document_type: str) -> str:
    low = (document_type or "").lower()

    if "organic_acids" in low:
        return (
            "Срочно обращаться за помощью нужно не из-за самого анализа, а если есть опасные симптомы: "
            "сильная слабость, повторная рвота, обезвоживание, судороги, нарушение сознания, "
            "резкое ухудшение состояния, сильная боль в животе или одышка."
        )

    return (
        "Срочно обращаться за помощью нужно не по факту наличия отклонений в бланке, а если есть "
        "опасные симптомы или резкое ухудшение состояния."
    )


def _default_note(document_type: str) -> str:
    low = (document_type or "").lower()
    if "organic_acids" in low:
        return "Этот анализ помогает определить направление дальнейшей оценки, но сам по себе не подтверждает диагноз."
    return "Этот анализ должен интерпретироваться вместе с жалобами, анамнезом и другими данными."


def _build_organic_acids_user_blocks(
    display_summary: str,
    summary_lines: List[str],
    groups: List[str],
    follow_checks: List[str],
    patient_type: str,
) -> List[Dict[str, Any]]:
    what_found: List[str] = []
    meaning: List[str] = []
    next_steps: List[str] = []

    if patient_type:
        what_found.append(f"По общему паттерну это {patient_type.lower()}.")
    if groups:
        what_found.append("Основные зоны внимания: " + ", ".join(groups[:3]).lower() + ".")
    if summary_lines:
        for line in summary_lines[:2]:
            if line.lower() not in " ".join(x.lower() for x in what_found):
                what_found.append(line)

    if groups:
        groups_blob = " ".join(groups).lower()

        if "энерг" in groups_blob:
            meaning.append("Есть признаки изменений, связанных с тем, как организм получает и использует энергию.")
        if "жир" in groups_blob or "β-окис" in groups_blob:
            meaning.append("Есть сигналы, которые врач может оценивать в контексте обмена жиров.")
        if "витамин" in groups_blob or "кофактор" in groups_blob:
            meaning.append("Есть неспецифичные признаки возможного витаминного или кофакторного дисбаланса.")
        if "внеш" in groups_blob or "ксенобиот" in groups_blob or "детокс" in groups_blob:
            meaning.append("Часть показателей может зависеть от внешних факторов: питания, лекарств, БАДов, бытовой химии.")
        if "глутатион" in groups_blob or "окислительный" in groups_blob:
            meaning.append("Есть отдельный сигнал возможного окислительного стресса.")
        if "азот" in groups_blob or "оротов" in groups_blob:
            meaning.append("Есть показатели, которые врач может оценивать в контексте азотистого обмена.")
    else:
        meaning.append("Анализ требует клинической оценки вместе с жалобами и анамнезом.")

    next_steps.append("Показать результат лечащему врачу или педиатру.")
    checks_blob = " ".join(follow_checks).lower()
    if any(k in checks_blob for k in ["питания", "интервалы", "голодания", "глюкоза"]):
        next_steps.append("Вспомнить режим питания: были ли большие интервалы между едой, плохой аппетит, ограничения в рационе.")
    if any(k in checks_blob for k in ["дефицит", "рацион", "витамин", "кофактор"]):
        next_steps.append("Обсудить с врачом, нужны ли проверки на дефицитные состояния и оценка рациона.")
    if any(k in checks_blob for k in ["лекарства", "бады", "бытов", "экспозиции", "среды"]):
        next_steps.append("Сообщить врачу о лекарствах, БАДах, бытовой химии и других возможных внешних воздействиях.")
    if any(k in checks_blob for k in ["повтор", "динамике", "контроль"]):
        next_steps.append("Если врач посчитает нужным, анализ можно оценить повторно в динамике.")

    return [
        {
            "title": "Что видно по анализу",
            "items": _dedup(what_found, limit=5) or [display_summary],
        },
        {
            "title": "Что это может значить простыми словами",
            "items": _dedup(meaning, limit=5) or [_default_note("organic_acids_urine")],
        },
        {
            "title": "Что делать дальше",
            "items": _dedup(next_steps, limit=5),
        },
        {
            "title": "Важно понимать",
            "items": [_default_note("organic_acids_urine")],
        },
    ]


def _build_generic_blocks(
    display_summary: str,
    summary_lines: List[str],
    follow_checks: List[str],
    document_type: str,
) -> List[Dict[str, Any]]:
    next_steps: List[str] = []
    if follow_checks:
        next_steps.append("Следующий шаг — показать результат врачу.")
        next_steps.extend(follow_checks)
    else:
        next_steps.append("Следующий шаг — показать результат врачу.")

    return [
        {
            "title": "Что видно по анализу",
            "items": summary_lines[:3] or [display_summary],
        },
        {
            "title": "Что делать дальше",
            "items": _dedup(next_steps, limit=10),
        },
        {
            "title": "Важно понимать",
            "items": [_default_note(document_type)],
        },
    ]


def build_unified_lab_report_presenter(
    *,
    filename: str,
    document_type: str,
    physician_report: Dict[str, Any],
    routing_output: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Единый presenter-слой для lab documents.
    Возвращает согласованный пакет:
    - display_summary
    - user_summary
    - case_summary
    - safe_next_steps
    - when_urgent
    - user_report_structured
    - user_report_text
    """
    routing_output = routing_output or {}
    user = routing_output.get("user") or {}
    doctor = routing_output.get("doctor") or {}

    summary_lines = _extract_summary_lines(physician_report)
    groups = _extract_group_names(physician_report)
    follow_checks = _extract_follow_checks(physician_report)
    hypotheses = _extract_hypotheses(physician_report)
    patient_type = _extract_patient_type(physician_report)
    brain_flags: List[str] = []
    brain_matched_ids: List[str] = []
    brain_report: Dict[str, Any] = {}
    knowledge_autolink: Dict[str, Any] = {}

    # Knowledge-pack now participates in interpreter output at lab-report stage.
    try:
        from app.services.ai_diagnostic_brain import (
            autolink_knowledge,
            build_full_report,
            derive_lab_flags,
            match_scenarios,
        )

        brain_flags = derive_lab_flags(physician_report)
        matched = match_scenarios(brain_flags)
        brain_matched_ids = [
            _s(x.get("scenario_id"))
            for x in matched
            if isinstance(x, dict) and _s(x.get("scenario_id"))
        ]
        knowledge_autolink = autolink_knowledge(
            {
                "report_type": "lab",
                "group": document_type,
                "lab_flags": brain_flags,
                "lab_markers": physician_report.get("abnormal_markers_table") or [],
                "symptoms": [],
                "profile": {},
                "current_hypotheses": hypotheses,
            }
        )
        brain_report = build_full_report(matched, knowledge_autolink=knowledge_autolink)
        hypotheses = _dedup(hypotheses + _labels_from_brain_hypotheses(brain_report.get("hypotheses") or []), limit=8)
        follow_checks = _dedup(
            follow_checks
            + [_s(x) for x in (brain_report.get("what_to_add") or []) if _s(x)]
            + [_s(x) for x in ((brain_report.get("plan") or {}).get("tests") or []) if _s(x)],
            limit=12,
        )
    except Exception:
        pass

    display_summary = _s(user.get("display_summary"))
    if not display_summary:
        display_summary = summary_lines[0] if summary_lines else f"Анализ по документу {filename} требует плановой клинической оценки."
    display_summary = _safe_short(display_summary, 180)

    # user summary
    user_summary_parts: List[str] = [display_summary]
    if patient_type:
        user_summary_parts.append(f"По общему паттерну это {patient_type.lower()}.")
    if groups:
        user_summary_parts.append("Основные зоны внимания: " + ", ".join(groups[:3]).lower() + ".")
    if summary_lines:
        for line in summary_lines[:2]:
            low_line = line.lower()
            if low_line not in " ".join(x.lower() for x in user_summary_parts):
                user_summary_parts.append(line)
    user_summary_parts.append(_default_note(document_type))
    user_summary = _safe_short(_sentences(user_summary_parts, limit=5), 560)

    # doctor / case summary
    case_summary_parts: List[str] = []
    routed_case = _s(doctor.get("routing_case_summary"))
    if routed_case:
        case_summary_parts.append(routed_case)
    else:
        if patient_type:
            case_summary_parts.append(f"Тип профиля: {patient_type}.")
        if groups:
            case_summary_parts.append("Основные затронутые группы: " + ", ".join(groups[:3]) + ".")
        if summary_lines:
            case_summary_parts.extend(summary_lines[:2])
        if hypotheses:
            case_summary_parts.append("Рабочие гипотезы: " + ", ".join(hypotheses[:3]) + ".")
    if not case_summary_parts:
        case_summary_parts.append(f"Отчёт по документу {filename} требует клинической интерпретации.")
    case_summary = _safe_short(_sentences(case_summary_parts, limit=5), 720)

    safe_next_steps = _s(user.get("safe_next_steps"))
    if not safe_next_steps:
        if follow_checks:
            # Canonical source: recommended_followup_table; без потерь (все пункты, до лимита длины)
            safe_next_steps = "Следующий шаг — обратиться к врачу. Полезно обсудить: " + "; ".join(follow_checks) + "."
        else:
            safe_next_steps = "Следующий шаг — показать результат лечащему врачу."
    brain_p1 = [_s(x) for x in ((brain_report.get("plan") or {}).get("priority_1") or []) if _s(x)]
    if brain_p1:
        safe_next_steps = (safe_next_steps + " Приоритет по сценарному слою: " + "; ".join(brain_p1[:2]) + ".").strip()
    safe_next_steps = _safe_short(safe_next_steps, 520)

    when_urgent = _s(user.get("when_urgent")) or _default_when_urgent(document_type)
    when_urgent = _safe_short(when_urgent, 420)

    if "organic_acids" in (document_type or "").lower():
        from app.services.clinical_action_engine import (
            build_organic_acids_blocks_from_clinical_actions,
        )
        from app.services.microbiome_guardrails import sanitize_microbiome_text

        clinical_blocks = build_organic_acids_blocks_from_clinical_actions(
            physician_report
        )
        if clinical_blocks:
            blocks = [
                {
                    "title": _s(b.get("title")),
                    "items": [
                        sanitize_microbiome_text(_s(x))
                        for x in (b.get("items") or [])
                        if _s(x)
                    ][:6],
                }
                for b in clinical_blocks
                if _s(b.get("title"))
            ]
        else:
            blocks = _build_organic_acids_user_blocks(
                display_summary=display_summary,
                summary_lines=summary_lines,
                groups=groups,
                follow_checks=follow_checks,
                patient_type=patient_type,
            )
    else:
        blocks = _build_generic_blocks(
            display_summary=display_summary,
            summary_lines=summary_lines,
            follow_checks=follow_checks,
            document_type=document_type,
        )

    user_report_structured = user.get("user_report_structured") or {
        "severity": "normal",
        "headline": display_summary,
        "blocks": blocks,
    }

    try:
        from app.services.gold_standard_report import (
            build_gold_standard_bundle,
            merge_gold_into_user_structured,
        )

        gold = build_gold_standard_bundle(
            physician_report=physician_report,
            document_type=document_type,
            filename=filename,
            display_summary=display_summary,
            follow_checks=follow_checks,
            hypotheses=hypotheses,
            safe_next_steps=safe_next_steps,
            when_urgent=when_urgent,
            case_summary=case_summary,
        )
        user_report_structured = merge_gold_into_user_structured(user_report_structured, gold)
    except Exception:
        pass

    return {
        "display_summary": display_summary,
        "user_summary": user_summary,
        "case_summary": case_summary,
        "safe_next_steps": safe_next_steps,
        "when_urgent": when_urgent,
        "user_report_structured": user_report_structured,
        "user_report_text": user_summary,
        "scenario_output": {
            "flags": brain_flags,
            "matched_scenarios": brain_matched_ids,
            "brain_report": brain_report,
            "knowledge_autolink": knowledge_autolink,
        },
        "presenter_debug": {
            "groups": groups,
            "hypotheses": hypotheses,
            "patient_type": patient_type,
            "follow_checks": follow_checks,
            "brain_flags_count": len(brain_flags),
            "brain_scenarios_count": len(brain_matched_ids),
            "autolink_sources_count": len(knowledge_autolink.get("knowledge_sources") or []),
        },
    }
