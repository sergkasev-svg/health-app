"""
Генерация PDF на бэкенде: отчёт и документ с поддержкой кириллицы.
"""
import io
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Имя зарегистрированного шрифта для кириллицы (один раз на модуль)
_CYRILLIC_FONT_NAME = "ReportCyrillic"


def _register_cyrillic_font() -> str:
    """Регистрирует шрифт с кириллицей. Возвращает имя шрифта для ParagraphStyle."""
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        return "Helvetica"
    try:
        if pdfmetrics.getFont(_CYRILLIC_FONT_NAME) is not None:
            return _CYRILLIC_FONT_NAME
    except Exception:
        pass
    win = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or "C:\\Windows"
    candidates = [
        Path(win) / "Fonts" / "arial.ttf",
        Path(win) / "Fonts" / "Arial.ttf",
        Path(win) / "Fonts" / "times.ttf",
        Path(win) / "Fonts" / "Times New Roman.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
    ]
    for path in candidates:
        if path.exists():
            try:
                pdfmetrics.registerFont(TTFont(_CYRILLIC_FONT_NAME, str(path)))
                logger.info("PDF: using font %s for Cyrillic", path)
                return _CYRILLIC_FONT_NAME
            except Exception as e:
                logger.debug("PDF: could not load %s: %s", path, e)
    logger.warning("PDF: no Cyrillic font found, Russian text may not display")
    return "Helvetica"


def _escape_for_paragraph(s: str) -> str:
    """Экранирует символы для reportlab Paragraph (HTML-подобный синтаксис)."""
    if not s:
        return ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _strip_html_to_text(html: str) -> str:
    """Убирает теги, заменяет br/p на переносы строк."""
    if not html:
        return ""
    s = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    s = re.sub(r"</p>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</div>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<div[^>]*>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"</h[1-6]>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<h[1-6][^>]*>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"</li>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<li[^>]*>", "• ", s, flags=re.IGNORECASE)
    s = re.sub(r"</ul>|</ol>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<ul[^>]*>|<ol[^>]*>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"</tr>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</t[dh]>", "\t", s, flags=re.IGNORECASE)
    s = re.sub(r"<t[dh][^>]*>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"&nbsp;", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"&amp;", "&", s, flags=re.IGNORECASE)
    s = re.sub(r"&lt;", "<", s, flags=re.IGNORECASE)
    s = re.sub(r"&gt;", ">", s, flags=re.IGNORECASE)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _parse_html_table_rows(table_html: str) -> list[list[str]]:
    """Extract text cells from HTML table markup."""
    rows: list[list[str]] = []
    for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", table_html or ""):
        cells = re.findall(r"(?is)<t[hd][^>]*>(.*?)</t[hd]>", tr)
        if not cells:
            continue
        row = []
        for c in cells:
            txt = _strip_html_to_text(c)
            txt = re.sub(r"\s+", " ", txt).strip()
            row.append(txt)
        if row:
            rows.append(row)
    return rows


def _prepare_html_for_pdf(html: str) -> str:
    """
    Убирает из HTML всё, что не должно попадать в PDF как текст:
    - полный документ: оставляем только содержимое <body>;
    - блоки <style>...</style> удаляются целиком, чтобы CSS не печатался на первых страницах.
    """
    if not html or not html.strip():
        return html or ""
    src = html.strip()
    # Удалить <style>...</style> (в т.ч. в одну строку и с переносами)
    src = re.sub(r"(?is)<style[^>]*>.*?</style>", "", src)
    # Если есть полный документ с <body>, брать только содержимое body
    body_match = re.search(r"(?is)<body[^>]*>(.*)</body\s*>", src)
    if body_match:
        src = body_match.group(1)
    return src


def _split_html_into_blocks(html: str) -> list[tuple[str, str]]:
    """
    Split HTML into ordered blocks:
    - ("text", "<html fragment>")
    - ("table", "<table ...>...</table>")
    Вызывающий код должен передавать уже подготовленный HTML (_prepare_html_for_pdf).
    """
    src = html or ""
    out: list[tuple[str, str]] = []
    pos = 0
    for m in re.finditer(r"(?is)<table[^>]*>.*?</table>", src):
        start, end = m.span()
        if start > pos:
            out.append(("text", src[pos:start]))
        out.append(("table", src[start:end]))
        pos = end
    if pos < len(src):
        out.append(("text", src[pos:]))
    return out


def build_pdf_report_like_user_tab(sections: list, date_str: str) -> bytes:
    """PDF один в один как в приложении: те же блоки, отступы, линия между блоками, серый бокс для документа."""
    buf = io.BytesIO()
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except ImportError:
        return b""
    try:
        font_name = _register_cyrillic_font()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
        )
        # Цвета как в приложении
        green = colors.HexColor("#0f766e")
        gray = colors.HexColor("#64748b")
        gray_bg = colors.HexColor("#f8fafc")
        gray_border = colors.HexColor("#e2e8f0")
        text_dark = colors.HexColor("#1e293b")
        content_width = 170 * mm
        # Заголовок страницы (как в приложении)
        title_style = ParagraphStyle(
            name="ReportTitle",
            fontName=font_name,
            fontSize=16,
            textColor=green,
            spaceAfter=3,
            alignment=1,
        )
        date_style = ParagraphStyle(
            name="ReportDate",
            fontName=font_name,
            fontSize=9,
            textColor=gray,
            spaceAfter=0,
        )
        # Заголовок секции: жирный, цвет тел/зелёный, отдельная строка, отступ снизу
        block_title_style = ParagraphStyle(
            name="BlockTitle",
            fontName=font_name,
            fontSize=12,
            textColor=green,
            spaceBefore=0,
            spaceAfter=6,
            leading=16,
        )
        # Имя документа: 0.9rem, серый
        doc_name_style = ParagraphStyle(
            name="DocName",
            fontName=font_name,
            fontSize=9,
            textColor=gray,
            spaceAfter=4,
        )
        # Подпись "Текст из документа (прочитан):"
        doc_label_style = ParagraphStyle(
            name="DocLabel",
            fontName=font_name,
            fontSize=9,
            textColor=gray,
            spaceAfter=2,
        )
        # Основной текст: читаемый межстрочный интервал
        body_style = ParagraphStyle(
            name="Body",
            fontName=font_name,
            fontSize=10,
            leading=18,
            spaceAfter=5,
            textColor=text_dark,
        )
        # Текст внутри серого бокса (report-extracted-text)
        box_text_style = ParagraphStyle(
            name="BoxText",
            fontName=font_name,
            fontSize=9,
            leading=14,
            spaceAfter=2,
            textColor=text_dark,
        )
        # Список: отступ слева, увеличенный интервал между пунктами
        list_style = ParagraphStyle(
            name="List",
            fontName=font_name,
            fontSize=10,
            leading=17,
            leftIndent=8 * mm,
            spaceAfter=5,
            textColor=text_dark,
        )
        # «Что делать дальше» — основной текст жирным
        next_style = ParagraphStyle(
            name="Next",
            fontName=font_name,
            fontSize=10,
            leading=18,
            spaceBefore=4,
            spaceAfter=6,
            textColor=text_dark,
        )
        disclaimer_style = ParagraphStyle(
            name="Disclaimer",
            fontName=font_name,
            fontSize=8,
            textColor=gray,
            spaceBefore=2,
            spaceAfter=0,
        )

        def block_title(s: str):
            return Paragraph("<b>" + _escape_for_paragraph((s or "").strip()) + "</b>", block_title_style)

        # Разделитель между секциями: большой отступ, линия, отступ — как на картинке
        def block_separator():
            out = []
            out.append(Spacer(1, 8 * mm))
            line_tbl = Table([[""]], colWidths=[content_width], rowHeights=[0.5 * mm])
            line_tbl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), gray_border)]))
            out.append(line_tbl)
            out.append(Spacer(1, 5 * mm))
            return out

        story = []
        story.append(Paragraph("Отчёт по анализу", title_style))
        if date_str:
            story.append(Paragraph(date_str.replace("_", " "), date_style))
        story.append(Spacer(1, 8 * mm))
        first = True
        for block in sections or []:
            kind = block.get("kind") or ""
            if not first:
                story.extend(block_separator())
            first = False
            if kind == "document":
                story.append(block_title("Документ"))
                story.append(Paragraph(_escape_for_paragraph(block.get("docName") or "Документ"), doc_name_style))
                extracted = (block.get("extractedText") or "").strip()
                if extracted:
                    story.append(Paragraph("Текст из документа (прочитан):", doc_label_style))
                    text_esc = _escape_for_paragraph(extracted[:8000]).replace("\n", "<br/>")
                    tbl = Table([[Paragraph(text_esc, box_text_style)]], colWidths=[content_width])
                    tbl.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, -1), gray_bg),
                        ("BOX", (0, 0), (-1, -1), 1, gray_border),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ]))
                    story.append(tbl)
                else:
                    story.append(Paragraph("Текст из документа не извлечён.", body_style))
                story.append(Spacer(1, 3 * mm))
            elif kind == "text":
                title = (block.get("title") or "").strip()
                if title:
                    story.append(block_title(title))
                text = (block.get("text") or "").strip()
                if text:
                    for part in text.split("\n\n"):
                        if part.strip():
                            story.append(Paragraph(_escape_for_paragraph(part).replace("\n", "<br/>"), body_style))
                story.append(Spacer(1, 2 * mm))
            elif kind == "list":
                title = (block.get("title") or "").strip()
                if title:
                    story.append(block_title(title))
                for item in block.get("items") or []:
                    if item and str(item).strip():
                        story.append(Paragraph("• " + _escape_for_paragraph(str(item).strip()).replace("\n", " "), list_style))
                story.append(Spacer(1, 2 * mm))
            elif kind == "next":
                story.append(block_title("Что делать дальше"))
                text = (block.get("text") or "").strip()
                if text:
                    story.append(Paragraph("<b>" + _escape_for_paragraph(text).replace("\n", "<br/>") + "</b>", next_style))
                story.append(Paragraph("Информация носит справочный характер и не заменяет консультацию врача.", disclaimer_style))
        if len(story) <= 3:
            story.append(Paragraph("Нет данных для отчёта.", body_style))
        doc.build(story)
        return buf.getvalue()
    except Exception as e:
        logger.exception("build_pdf_report_like_user_tab failed: %s", e)
        return b""


def build_pdf_report(
    user_html: str, doctor_html: str, doc_name: str, date_str: str, for_doctor: bool = False
) -> bytes:
    """Резервный PDF из HTML: структурированно по абзацам. Если for_doctor — заголовок «Отчёт для врача»."""
    buf = io.BytesIO()
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except ImportError:
        logger.warning("reportlab not installed")
        return b""
    try:
        font_name = _register_cyrillic_font()
        html_src = user_html or ""
        if not html_src.strip() and (doctor_html or "").strip():
            html_src = doctor_html
        html_src = _prepare_html_for_pdf(html_src)
        blocks = _split_html_into_blocks(html_src)

        use_landscape = False
        for kind, chunk in blocks:
            if kind != "table":
                continue
            rows = _parse_html_table_rows(chunk)
            if not rows:
                continue
            col_count = max(len(r) for r in rows)
            longest = max((len(str(c or "")) for r in rows[:120] for c in r), default=0)
            if col_count >= 5 or longest >= 90:
                use_landscape = True
                break

        doc = SimpleDocTemplate(
            buf,
            pagesize=landscape(A4) if use_landscape else A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
        )
        green = colors.HexColor("#0f766e")
        gray = colors.HexColor("#64748b")
        title_style = ParagraphStyle(
            name="ReportTitle",
            fontName=font_name,
            fontSize=14,
            textColor=green,
            spaceAfter=2,
            alignment=1,
        )
        date_style = ParagraphStyle(
            name="ReportDate",
            fontName=font_name,
            fontSize=9,
            textColor=gray,
            spaceAfter=8,
        )
        body_style = ParagraphStyle(
            name="ReportBody",
            fontName=font_name,
            fontSize=10,
            leading=16,
            spaceAfter=6,
            textColor=colors.HexColor("#1e293b"),
        )
        section_header_style = ParagraphStyle(
            name="ReportSectionHeader",
            fontName=font_name,
            fontSize=11,
            leading=14,
            spaceBefore=8,
            spaceAfter=4,
            textColor=green,
        )
        table_cell_style = ParagraphStyle(
            name="ReportTableCell",
            fontName=font_name,
            fontSize=8 if use_landscape else 9,
            leading=11 if use_landscape else 12,
            textColor=colors.HexColor("#1e293b"),
        )
        table_head_style = ParagraphStyle(
            name="ReportTableHead",
            fontName=font_name,
            fontSize=8 if use_landscape else 9,
            leading=11 if use_landscape else 12,
            textColor=colors.HexColor("#0f172a"),
        )
        story = []
        title_text = "Отчёт для врача" if for_doctor else "Отчёт по анализу"
        story.append(Paragraph(title_text, title_style))
        story.append(Paragraph(date_str.replace("_", " "), date_style))
        story.append(Spacer(1, 8 * mm))
        if not blocks:
            text = _strip_html_to_text(html_src)
            section_headers = ("Анамнез", "Выводы", "Гипотезы", "Диагноз", "План лечения", "Индекс тяжести", "Рекомендации", "Когда срочно")
            for part in text.split("\n\n"):
                part = part.strip()
                if not part:
                    continue
                first_line = part.split("\n")[0].strip()
                if first_line in section_headers and "\n" in part:
                    header = _escape_for_paragraph(first_line)
                    rest = "\n".join(part.split("\n")[1:]).strip()
                    story.append(Paragraph("<b>" + header + "</b>", section_header_style))
                    if rest:
                        story.append(Paragraph(_escape_for_paragraph(rest).replace("\n", "<br/>"), body_style))
                else:
                    story.append(Paragraph(_escape_for_paragraph(part).replace("\n", "<br/>"), body_style))
        else:
            for kind, chunk in blocks:
                if kind == "text":
                    text = _strip_html_to_text(chunk)
                    for part in text.split("\n\n"):
                        if part.strip():
                            story.append(Paragraph(_escape_for_paragraph(part).replace("\n", "<br/>"), body_style))
                    continue
                rows = _parse_html_table_rows(chunk)
                if not rows:
                    continue
                col_count = max(len(r) for r in rows)
                norm_rows: list[list[str]] = []
                for r in rows:
                    rr = list(r) + ([""] * (col_count - len(r)))
                    norm_rows.append(rr[:col_count])
                weights: list[float] = []
                for ci in range(col_count):
                    max_len = 0
                    for rr in norm_rows[:200]:
                        max_len = max(max_len, len(str(rr[ci] or "")))
                    weights.append(float(max(8, min(max_len, 64))))
                total_weight = sum(weights) or 1.0
                col_widths = [float(doc.width) * (w / total_weight) for w in weights]
                tbl_data = []
                for ri, r in enumerate(norm_rows):
                    row_cells = []
                    for cell in r:
                        style = table_head_style if ri == 0 else table_cell_style
                        row_cells.append(Paragraph(_escape_for_paragraph(cell).replace("\n", "<br/>"), style))
                    tbl_data.append(row_cells)
                tbl = Table(tbl_data, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
                tbl.setStyle(TableStyle([
                    ("GRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#e2e8f0")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
                    ("FONTNAME", (0, 0), (-1, 0), font_name),
                    ("FONTNAME", (0, 1), (-1, -1), font_name),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]))
                story.append(tbl)
                story.append(Spacer(1, 3 * mm))
        doc.build(story)
        return buf.getvalue()
    except Exception as e:
        logger.exception("build_pdf_report failed: %s", e)
        return b""


def build_pdf_document(title: str, body: str, date_str: str) -> bytes:
    """Собирает PDF документа (прочитанный текст) для удобного чтения."""
    buf = io.BytesIO()
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    except ImportError:
        return b""
    try:
        font_name = _register_cyrillic_font()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
        )
        green = colors.HexColor("#0f766e")
        gray = colors.HexColor("#64748b")
        title_style = ParagraphStyle(
            name="DocTitle",
            fontName=font_name,
            fontSize=14,
            textColor=green,
            spaceAfter=6,
        )
        body_style = ParagraphStyle(
            name="DocBody",
            fontName=font_name,
            fontSize=10,
            leading=16,
            spaceAfter=4,
            textColor=colors.HexColor("#1e293b"),
        )
        story = []
        story.append(Paragraph(_escape_for_paragraph(title or "Документ"), title_style))
        if date_str:
            date_style = ParagraphStyle(
                name="DocDate",
                fontName=font_name,
                fontSize=9,
                textColor=gray,
                spaceAfter=8,
            )
            story.append(Paragraph(date_str.replace("_", " "), date_style))
        story.append(Spacer(1, 4 * mm))
        for part in (body or "").split("\n\n"):
            if part.strip():
                story.append(Paragraph(_escape_for_paragraph(part).replace("\n", "<br/>"), body_style))
        doc.build(story)
        return buf.getvalue()
    except Exception as e:
        logger.exception("build_pdf_document failed: %s", e)
        return b""
