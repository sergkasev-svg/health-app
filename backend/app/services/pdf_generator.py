"""
Premium PDF-генератор из результата анализа (hypotheses, plan).
Стиль: краткий итог, карточки метрик, клиническая логика, план по приоритетам, что проверить.
Шрифты берутся из приложения (pdf_export) — работает на Windows и Linux.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _get_font_name() -> str:
    """Один шрифт с кириллицей для всего PDF (Windows/Linux)."""
    try:
        from app.services.pdf_export import _register_cyrillic_font
        return _register_cyrillic_font()
    except Exception:
        return "Helvetica"


def _escape(s: str) -> str:
    if not s:
        return ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _styles():
    font_name = _get_font_name()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="AppTitle",
        fontName=font_name,
        fontSize=24,
        leading=30,
        textColor=colors.HexColor("#122033"),
        spaceAfter=10,
    ))
    styles.add(ParagraphStyle(
        name="AppSubtitle",
        fontName=font_name,
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#5f6f86"),
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="SectionTitle",
        fontName=font_name,
        fontSize=15,
        leading=20,
        textColor=colors.HexColor("#0f766e"),
        spaceBefore=8,
        spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="Body",
        fontName=font_name,
        fontSize=10.3,
        leading=14.5,
        textColor=colors.HexColor("#122033"),
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="Muted",
        fontName=font_name,
        fontSize=9.2,
        leading=12.5,
        textColor=colors.HexColor("#5f6f86"),
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="CardTitle",
        fontName=font_name,
        fontSize=11.2,
        leading=14.5,
        textColor=colors.HexColor("#122033"),
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="MetricValue",
        fontName=font_name,
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#122033"),
        alignment=1,
    ))
    styles.add(ParagraphStyle(
        name="MetricLabel",
        fontName=font_name,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#5f6f86"),
        alignment=1,
    ))
    return styles


def _safe_lines(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    s = str(value).strip()
    return [s] if s else []


def _box(styles, title: str, lines: List[str], width=170 * mm, bg="#ffffff", border="#dbe3ee"):
    body = "<br/>".join(_escape(x) for x in (lines or ["—"]))
    tbl = Table([
        [Paragraph(_escape(title), styles["CardTitle"])],
        [Paragraph(body, styles["Body"])],
    ], colWidths=[width])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor(border)),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return tbl


def _metric_card(styles, label: str, value: str, tone: str):
    bg = {
        "bad": "#fff1f2",
        "good": "#ecfdf5",
        "neutral": "#f8fafc",
    }.get(tone, "#f8fafc")
    border = {
        "bad": "#fecdd3",
        "good": "#bbf7d0",
        "neutral": "#dbe3ee",
    }.get(tone, "#dbe3ee")
    tbl = Table([
        [Paragraph(_escape(value), styles["MetricValue"])],
        [Paragraph(_escape(label), styles["MetricLabel"])],
    ], colWidths=[52 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor(border)),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return tbl


def _metrics_row(styles, metrics: List[Dict[str, str]]):
    cards = []
    for item in metrics[:3]:
        cards.append(_metric_card(
            styles=styles,
            label=str(item.get("label", "Показатель")),
            value=str(item.get("value", "—")),
            tone=str(item.get("tone", "neutral")),
        ))
    while len(cards) < 3:
        cards.append(_metric_card(styles, "Показатель", "—", "neutral"))
    row = Table([cards], colWidths=[56 * mm, 56 * mm, 56 * mm])
    row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    return row


def _bullets(styles, items: List[str]):
    items = items or ["—"]
    return ListFlowable(
        [ListItem(Paragraph(_escape(x), styles["Body"])) for x in items],
        bulletType="bullet",
        leftIndent=16,
    )


def build_pdf_data(result: Dict[str, Any], meta: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Собирает данные для PDF из результата API (hypotheses, plan)."""
    meta = meta or {}
    hypotheses = result.get("hypotheses") or []
    plan = result.get("plan") or {}
    findings = [h.get("label", "") for h in hypotheses if isinstance(h, dict)]
    meanings = [h.get("meaning", "") for h in hypotheses if isinstance(h, dict) and h.get("meaning")]
    tests = _safe_lines(plan.get("tests"))

    summary = findings[:3] or ["Система не собрала выраженных автоматических гипотез."]
    priority_1 = _safe_lines(plan.get("priority_1"))[:4]
    priority_2 = _safe_lines(plan.get("priority_2"))[:4]

    metrics = meta.get("metrics") or [
        {"label": "Гипотез", "value": str(len(findings) or 0), "tone": "neutral"},
        {"label": "Шагов", "value": str(len(priority_1) + len(priority_2)), "tone": "good" if priority_1 else "neutral"},
        {"label": "Проверок", "value": str(len(tests)), "tone": "neutral"},
    ]

    return {
        "report_id": meta.get("report_id") or f"ZZ-{uuid4().hex[:8].upper()}",
        "date": meta.get("date") or "",
        "patient": meta.get("patient") or "—",
        "title": meta.get("title") or "За Здоровье - Premium PDF отчёт",
        "subtitle": meta.get("subtitle") or "Персональная интерпретация анализа и план следующих шагов",
        "summary": summary,
        "metrics": metrics,
        "findings_blocks": [
            {
                "title": "Что происходит",
                "lines": findings or ["Система не выделила отдельный клинический паттерн."],
            },
            {
                "title": "Что это значит",
                "lines": meanings or ["Отклонения нужно оценивать вместе с жалобами, анамнезом и другими данными."],
            },
        ],
        "plan_blocks": [
            {
                "title": "Приоритет 1 - ближайшие 7 дней",
                "lines": priority_1 or ["Пока нет сформированных шагов первой очереди."],
            },
            {
                "title": "Приоритет 2 - следующие 2-4 недели",
                "lines": priority_2 or ["Следующие шаги появятся после уточнения контекста или premium-доступа."],
            },
        ],
        "tests": tests or ["Дополнительные проверки не сформированы."],
        "important": [
            "Это не диагноз и не назначение лечения.",
            "Интерпретация зависит от жалоб, возраста, анамнеза, лекарств и очной оценки врача.",
        ],
    }


def _build_story(story, data: Dict[str, Any], styles) -> None:
    story.append(Paragraph(_escape(data["title"]), styles["AppTitle"]))
    story.append(Paragraph(_escape(data["subtitle"]), styles["AppSubtitle"]))
    story.append(Paragraph(
        _escape(f"Дата: {data['date'] or '—'}   ID отчёта: {data['report_id']}   Пациент: {data['patient']}"),
        styles["Muted"],
    ))
    story.append(Spacer(1, 10))
    story.append(_box(styles, "Краткий итог", data["summary"], bg="#f8fafc"))
    story.append(Spacer(1, 10))
    story.append(_metrics_row(styles, data["metrics"]))
    story.append(Spacer(1, 14))
    story.append(Paragraph(_escape("Важно"), styles["SectionTitle"]))
    story.append(_box(styles, "Ограничения интерпретации", data["important"], bg="#fff7ed", border="#fed7aa"))
    story.append(PageBreak())
    story.append(Paragraph(_escape("Клиническая логика отчёта"), styles["SectionTitle"]))
    for block in data["findings_blocks"]:
        story.append(_box(styles, block["title"], block["lines"]))
        story.append(Spacer(1, 8))
    story.append(Paragraph(_escape("План действий"), styles["SectionTitle"]))
    for block in data["plan_blocks"]:
        story.append(_box(styles, block["title"], block["lines"], bg="#f0fdfa", border="#c9efe6"))
        story.append(Spacer(1, 8))
    story.append(Paragraph(_escape("Что проверить"), styles["SectionTitle"]))
    story.append(_bullets(styles, data["tests"]))


def generate_premium_pdf(result: Dict[str, Any], output_path: str, meta: Dict[str, Any] | None = None) -> str:
    """Генерирует PDF и сохраняет в output_path. Возвращает путь к файлу."""
    styles = _styles()
    data = build_pdf_data(result, meta)
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    story = []
    _build_story(story, data, styles)
    doc.build(story)
    return output_path


def build_premium_pdf_bytes(result: Dict[str, Any], meta: Dict[str, Any] | None = None) -> bytes:
    """Генерирует PDF в память. Для отдачи через API (файл без сохранения на диск)."""
    styles = _styles()
    data = build_pdf_data(result, meta)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    story = []
    _build_story(story, data, styles)
    doc.build(story)
    return buf.getvalue()
