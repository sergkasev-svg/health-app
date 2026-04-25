"""
Генератор PDF персонального отчёта по состоянию организма.
Структурированный отчёт с планом: что происходит → что значит → что делать → что проверить → важно.
Выглядит как платный продукт клиники. Поддержка кириллицы через pdf_export.
"""
from __future__ import annotations

import io
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _escape(s: str) -> str:
    if not s:
        return ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _data_to_lists(data: Dict[str, Any]) -> Dict[str, List[str]]:
    """Нормализует data: все значения — списки строк."""
    out: Dict[str, List[str]] = {
        "problems": [],
        "meaning": [],
        "actions": [],
        "tests": [],
    }
    for key in out:
        val = data.get(key)
        if isinstance(val, list):
            out[key] = [str(x).strip() for x in val if str(x).strip()]
        elif val:
            out[key] = [str(val).strip()]
    return out


def generate_pdf_report(filename: str | None, data: Dict[str, Any]) -> bytes:
    """
    Генерирует PDF отчёт. Если filename передан — не используется (для совместимости с API).
    Возвращает bytes PDF. data: problems, meaning, actions, tests (списки строк).
    """
    buf = io.BytesIO()
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError:
        logger.warning("reportlab not installed")
        return b""

    try:
        from app.services.pdf_export import _register_cyrillic_font

        font_name = _register_cyrillic_font()
    except Exception:
        font_name = "Helvetica"

    normalized = _data_to_lists(data)
    problems = normalized["problems"] or ["По анализу выявлены изменения, требующие оценки врача."]
    meaning = normalized["meaning"] or ["Интерпретация возможна только вместе с клинической картиной."]
    actions = normalized["actions"] or ["Показать результат врачу."]
    tests = normalized["tests"] or ["По назначению врача."]
    important = [
        "Этот отчёт не является диагнозом.",
        "Рекомендуется консультация врача для интерпретации и дальнейших шагов.",
    ]

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    title_style = ParagraphStyle(
        name="PersonalTitle",
        fontName=font_name,
        fontSize=16,
        textColor=colors.HexColor("#0f766e"),
        spaceAfter=14,
        spaceBefore=0,
    )
    heading_style = ParagraphStyle(
        name="PersonalHeading",
        fontName=font_name,
        fontSize=12,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=6,
        spaceBefore=12,
    )
    normal_style = ParagraphStyle(
        name="PersonalNormal",
        fontName=font_name,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#334155"),
        spaceAfter=4,
        leftIndent=0,
    )

    elements: List[Any] = []

    def add_title(text: str) -> None:
        elements.append(Paragraph(_escape(text), title_style))
        elements.append(Spacer(1, 12))

    def add_section(title: str, items: List[str]) -> None:
        elements.append(Paragraph(f"<b>{_escape(title)}</b>", heading_style))
        elements.append(Spacer(1, 6))
        for i in items:
            if i.strip():
                elements.append(Paragraph("• " + _escape(i), normal_style))
        elements.append(Spacer(1, 10))

    add_title("Персональный отчёт по состоянию организма")
    add_section("Что происходит", problems)
    add_section("Что это значит", meaning)
    add_section("Что делать", actions)
    add_section("Что проверить", tests)
    add_section("Важно", important)

    doc.build(elements)
    return buf.getvalue()


def build_personal_report_pdf_bytes(data: Dict[str, Any]) -> bytes:
    """Удобная обёртка: data → PDF bytes. Для сохранения в файл или отдачи в API."""
    return generate_pdf_report(None, data)


def report_to_pdf_data(report: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Собирает data для PDF из physician report (organic acids) или unified report.
    Использует summary, treatment_plan, possible_correction_directions, clinical_action.
    """
    problems: List[str] = []
    meaning: List[str] = []
    actions: List[str] = []
    tests: List[str] = []

    summary = report.get("summary") or []
    for line in summary[:5]:
        s = str(line or "").strip()
        if s and ("паттерн" in s.lower() or "перегрузк" in s or "стресс" in s or "кофактор" in s or "энерг" in s):
            problems.append(s)
    if not problems and summary:
        problems.extend([str(x).strip() for x in summary[:3] if str(x).strip()])
    if not problems:
        problems.append("По анализу выявлены изменения, требующие оценки врача.")

    plan = report.get("treatment_plan") or {}
    actions.extend(plan.get("core_actions") or [])
    actions.extend(plan.get("lifestyle") or [])
    tests.extend(plan.get("tests") or [])
    for rec in (plan.get("nutrition") or [])[:4]:
        actions.append(rec)

    correction = report.get("possible_correction_directions") or []
    for block in correction:
        if isinstance(block, dict):
            title = str(block.get("title") or "").strip()
            rec = block.get("recommended") or block.get("text") or []
            if title:
                actions.append(title + ": " + "; ".join(str(x) for x in rec[:3]))
            else:
                actions.extend([str(x) for x in rec[:4] if str(x).strip()])
        else:
            actions.append(str(block).strip())

    try:
        from app.services.clinical_action_engine import (
            build_what_it_means,
            build_actions,
            derive_markers_from_physician_report,
        )
        markers = derive_markers_from_physician_report(report)
        meaning.extend(build_what_it_means(markers))
        act = build_actions(markers)
        if not actions:
            actions.extend(act.get("priority_now") or ["Показать результат врачу."])
        if not tests:
            tests.extend(act.get("tests_to_confirm") or ["По назначению врача."])
    except Exception:
        pass
    if not meaning:
        meaning.append("Интерпретация возможна только вместе с клинической картиной и очной оценкой врача.")

    return {
        "problems": problems[:6],
        "meaning": meaning[:5],
        "actions": list(dict.fromkeys(actions))[:12],
        "tests": list(dict.fromkeys(tests))[:8],
    }


# --- Premium PDF (уровень клиника / платный отчёт) ---

def _premium_styles(font_name: str) -> Dict[str, Any]:
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle

    return {
        "CoverBrand": ParagraphStyle(
            name="CoverBrand",
            fontSize=12,
            leading=16,
            spaceAfter=6,
            textColor=colors.HexColor("#0F766E"),
            fontName=font_name,
        ),
        "CoverTitle": ParagraphStyle(
            name="CoverTitle",
            fontSize=22,
            leading=28,
            spaceAfter=14,
            textColor=colors.HexColor("#1F2937"),
            fontName=font_name,
        ),
        "CoverSub": ParagraphStyle(
            name="CoverSub",
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#6B7280"),
            spaceAfter=20,
            fontName=font_name,
        ),
        "SectionTitle": ParagraphStyle(
            name="SectionTitle",
            fontSize=15,
            leading=20,
            textColor=colors.HexColor("#0F766E"),
            spaceBefore=14,
            spaceAfter=8,
            fontName=font_name,
        ),
        "BodyTextCustom": ParagraphStyle(
            name="BodyTextCustom",
            fontSize=10.5,
            leading=15,
            textColor=colors.HexColor("#111827"),
            spaceAfter=6,
            fontName=font_name,
        ),
        "Muted": ParagraphStyle(
            name="Muted",
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor("#6B7280"),
            spaceAfter=6,
            fontName=font_name,
        ),
        "CardTitle": ParagraphStyle(
            name="CardTitle",
            fontSize=11.5,
            leading=15,
            textColor=colors.HexColor("#111827"),
            spaceAfter=4,
            fontName=font_name,
        ),
    }


def _premium_card_table(title: str, lines: List[str], styles: Dict[str, Any]) -> Any:
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table, TableStyle

    content = [
        [Paragraph(f"<b>{_escape(title)}</b>", styles["CardTitle"])],
        [Paragraph("<br/>".join(_escape(x) for x in (lines or [])), styles["BodyTextCustom"])],
    ]
    table = Table(content, colWidths=[170 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#E5E7EB")),
                ("INNERPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _premium_bullet_list(items: List[str], styles: Dict[str, Any]) -> List[Any]:
    from reportlab.platypus import Paragraph

    out: List[Any] = []
    for x in items or []:
        if str(x).strip():
            out.append(Paragraph("• " + _escape(x), styles["BodyTextCustom"]))
    return out


def generate_premium_pdf(filename: str | None, data: Dict[str, Any]) -> bytes:
    """
    Генерирует premium PDF: обложка, краткий итог, что обнаружено (карточки),
    что значит, план по приоритетам, что проверить, питание, важно.
    data: date, report_id, summary, top_actions, findings[{title, lines}], meaning, plan[{title, lines}], tests, lifestyle, important.
    """
    buf = io.BytesIO()
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import PageBreak, SimpleDocTemplate, Spacer
    except ImportError:
        logger.warning("reportlab not installed")
        return b""
    try:
        from app.services.pdf_export import _register_cyrillic_font
        font_name = _register_cyrillic_font()
    except Exception:
        font_name = "Helvetica"

    styles = _premium_styles(font_name)
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    from reportlab.platypus import Paragraph

    story: List[Any] = []
    brand_name = str(data.get("brand_name") or "За Здоровье").strip()

    story.append(Paragraph(_escape(brand_name), styles["CoverBrand"]))
    story.append(Paragraph("Персональный метаболический отчёт", styles["CoverTitle"]))
    story.append(Paragraph("Интерпретация лабораторных данных и план следующих шагов", styles["CoverSub"]))
    story.append(Paragraph(f"Дата: {_escape(str(data.get('date') or '-'))}", styles["Muted"]))
    story.append(Paragraph(f"ID отчёта: {_escape(str(data.get('report_id') or '-'))}", styles["Muted"]))
    story.append(Spacer(1, 16))

    summary = data.get("summary") or ["По анализу выявлены изменения. Требуется оценка врача."]
    story.append(_premium_card_table("Краткий итог", summary[:5], styles))
    story.append(Spacer(1, 12))
    top_actions = data.get("top_actions") or ["Показать результат врачу."]
    story.append(_premium_card_table("Главные шаги", top_actions[:5], styles))
    story.append(PageBreak())

    story.append(Paragraph("Что обнаружено", styles["SectionTitle"]))
    for block in data.get("findings") or []:
        title = str(block.get("title") or "").strip()
        lines = block.get("lines") or []
        if title or lines:
            story.append(_premium_card_table(title or "Находки", lines, styles))
            story.append(Spacer(1, 8))

    meaning = data.get("meaning") or ["Интерпретация возможна только вместе с клинической картиной."]
    story.append(Paragraph("Что это значит", styles["SectionTitle"]))
    for p in _premium_bullet_list(meaning, styles):
        story.append(p)
    story.append(Spacer(1, 10))

    story.append(Paragraph("План действий", styles["SectionTitle"]))
    for phase in data.get("plan") or []:
        title = str(phase.get("title") or "").strip()
        lines = phase.get("lines") or []
        if title or lines:
            story.append(_premium_card_table(title, lines, styles))
            story.append(Spacer(1, 8))

    tests = data.get("tests") or ["По назначению врача."]
    story.append(Paragraph("Что проверить", styles["SectionTitle"]))
    for p in _premium_bullet_list(tests, styles):
        story.append(p)
    story.append(Spacer(1, 10))

    lifestyle = data.get("lifestyle") or ["Режим питания и образ жизни — по рекомендации врача."]
    story.append(Paragraph("Питание и образ жизни", styles["SectionTitle"]))
    for p in _premium_bullet_list(lifestyle, styles):
        story.append(p)
    story.append(Spacer(1, 10))

    important = data.get("important") or [
        "Этот отчёт не является диагнозом.",
        "Окончательная интерпретация зависит от жалоб, анамнеза и очной оценки врача.",
    ]
    story.append(Paragraph("Важно", styles["SectionTitle"]))
    for p in _premium_bullet_list(important, styles):
        story.append(p)

    doc.build(story)
    return buf.getvalue()


def build_premium_pdf_bytes(data: Dict[str, Any]) -> bytes:
    """Premium PDF в bytes для API/файла."""
    return generate_premium_pdf(None, data)


def report_to_premium_pdf_data(report: Dict[str, Any], *, report_id: str = "", date_str: str = "") -> Dict[str, Any]:
    """
    Собирает data для premium PDF из physician/unified report.
    Обложка, краткий итог, findings по доменам, meaning, план по приоритетам, tests, lifestyle, important.
    """
    from datetime import datetime

    summary: List[str] = []
    for line in report.get("summary") or []:
        s = str(line or "").strip()
        if s:
            summary.append(s)
    if not summary:
        summary.append("По анализу выявлены изменения. Требуется оценка врача.")

    plan = report.get("treatment_plan") or {}
    top_actions: List[str] = []
    top_actions.extend(plan.get("core_actions") or [])
    top_actions.extend(plan.get("lifestyle") or [])
    if not top_actions:
        top_actions.append("Показать результат врачу.")
    top_actions = list(dict.fromkeys(top_actions))[:5]

    findings: List[Dict[str, Any]] = []
    domain_findings = [
        ("Внешняя метаболическая нагрузка", "Повышенные маркеры могут соответствовать влиянию питания, добавок, бытовой химии. Нужно разобрать возможные источники нагрузки."),
        ("Окислительный стресс", "Признаки напряжения антиоксидантной системы. Может ухудшать восстановление и переносимость нагрузок."),
        ("Энергообмен", "Маркеры могут указывать на менее эффективное использование жиров и особенности энергетического обмена."),
        ("Витаминно-кофакторный блок", "Возможный вклад дефицита витаминов или кофакторов. Требуется подтверждение анализами."),
    ]
    ranked = (report.get("clinical_scores") or {}).get("ranked_domains") or []
    keys = [str(d.get("key") or "") for d in ranked[:4]]
    if "xenobiotics" in keys:
        findings.append({"title": domain_findings[0][0], "lines": [domain_findings[0][1]]})
    if "glutathione" in keys:
        findings.append({"title": domain_findings[1][0], "lines": [domain_findings[1][1]]})
    if "energy" in keys or "beta_oxidation" in keys:
        findings.append({"title": domain_findings[2][0], "lines": [domain_findings[2][1]]})
    if "cofactors" in keys:
        findings.append({"title": domain_findings[3][0], "lines": [domain_findings[3][1]]})
    if not findings:
        findings.append({"title": "Изменения в профиле", "lines": [summary[0] if summary else "Требуется клиническая оценка."]})

    meaning: List[str] = []
    try:
        from app.services.clinical_action_engine import build_what_it_means, derive_markers_from_physician_report
        markers = derive_markers_from_physician_report(report)
        meaning = build_what_it_means(markers)
    except Exception:
        pass
    if not meaning:
        meaning = [
            "Организм может работать в режиме перегрузки.",
            "Это способно проявляться слабостью, утомляемостью и ухудшением восстановления.",
            "Важно не только досдать анализы, но и убрать возможные провоцирующие факторы.",
        ]

    priority_now = []
    nutrition = []
    try:
        from app.services.clinical_action_engine import build_actions, derive_markers_from_physician_report
        markers = derive_markers_from_physician_report(report)
        act = build_actions(markers)
        priority_now = act.get("priority_now") or []
        nutrition = act.get("nutrition") or []
    except Exception:
        pass
    tests = list(dict.fromkeys(plan.get("tests") or []))
    if not tests:
        tests = ["B12", "Фолиевая кислота", "Гомоцистеин", "По показаниям: ферритин, витамин D, глюкоза/инсулин"]

    plan_phases = [
        {"title": "Приоритет 1 — ближайшие 3–7 дней", "lines": priority_now[:5] or ["Упростить рацион.", "Сократить бытовую химию.", "Не пропускать приёмы пищи."]},
        {"title": "Приоритет 2 — 2–4 недели", "lines": ["Оценить достаточность калорий и белка.", "Обсудить с врачом подтверждение дефицитов B12/B9.", "Отследить динамику самочувствия."]},
        {"title": "Приоритет 3 — долгосрочно", "lines": ["Поддерживать стабильный режим питания.", "Снижать лишнюю метаболическую нагрузку.", "Корректировать выявленные дефициты по результатам подтверждения."]},
    ]
    if priority_now:
        plan_phases[0]["lines"] = priority_now[:5]

    lifestyle = nutrition[:5] or [
        "Регулярное питание без длительных голодовок.",
        "Меньше ультрапереработанной пищи.",
        "Осторожнее с лишними БАДами и ароматизированной бытовой химией.",
    ]

    return {
        "brand_name": "За Здоровье",
        "date": date_str or datetime.now().strftime("%Y-%m-%d"),
        "report_id": report_id or ("OA-" + datetime.now().strftime("%Y-%m%d") + "-001"),
        "summary": summary[:5],
        "top_actions": top_actions,
        "findings": findings,
        "meaning": meaning[:5],
        "plan": plan_phases,
        "tests": tests[:8],
        "lifestyle": lifestyle,
        "important": [
            "Этот отчёт не является диагнозом.",
            "Окончательная интерпретация зависит от жалоб, анамнеза и очной оценки врача.",
        ],
    }
