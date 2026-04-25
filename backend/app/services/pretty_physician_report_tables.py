"""
Лабораторный HTML-рендер physician report.
Стиль ближе к реальному лабораторному бланку:
- строгая шапка
- секции как в анализах
- минимум декоративности
- фокус на читаемости и печати в PDF
- поддержка блока possible_correction_directions
"""
from __future__ import annotations

import html
from datetime import date
from typing import Any, Dict, Iterable, List

# Один источник правды для заголовка отчёта (избегаем дубля в шаблоне)
REPORT_TITLE = "Отчёт для врача"


def ensure_list(value: Any) -> List[str]:
    """Нормализация поля в список строк для безопасного join. Устраняет баг 'H, b, ,, R, B, C' при str вместо list."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(value).strip()] if str(value).strip() else []


def _esc(x: Any) -> str:
    return html.escape(str(x if x is not None else ""))


def _s(x: Any) -> str:
    return str(x if x is not None else "").strip()


def _flag_symbol(flag: str) -> str:
    f = _s(flag).lower()
    if f == "high":
        return "↑"
    if f == "low":
        return "↓"
    if "border" in f or "near" in f:
        return "≈"
    return ""


def _flag_label(flag: str) -> str:
    f = _s(flag).lower()
    if f == "high":
        return "выше нормы"
    if f == "low":
        return "ниже нормы"
    if f == "borderline_high":
        return "погранично выше нормы"
    if f == "borderline_low":
        return "погранично ниже нормы"
    if "significant_high" in f or "significant high" in f:
        return "значимое повышение"
    if "significant_low" in f or "significant low" in f:
        return "значимое снижение"
    if "border" in f or "near" in f:
        return "погранично"
    return "норма"


def _friendly_doc_type_label(document_type: str, report_data: Dict[str, Any] | None = None) -> str:
    """Краткая подпись типа анализа для пациента и шапки (без внутренних id)."""
    ds = {}
    if isinstance(report_data, dict):
        ds = report_data.get("document_summary") or {}
        if not isinstance(ds, dict):
            ds = {}
    if ds.get("combined_oak_lipid_panel"):
        # Один PDF: липиды + гематология/вит. D/др. — не подписывать как «только липидный профиль»
        return (
            "Комплексный лабораторный бланк крови "
            "(на одном документе — липиды и другие показатели; см. таблицу отклонений)"
        )

    low = (document_type or "").lower()
    if "urinalysis" in low or low == "urine" or ("urine" in low and "organic" not in low):
        return "Общий анализ мочи (ОАМ)"
    if "cbc_with_retic" in low:
        return "Общеклинический анализ крови с лейкоцитарной формулой и ретикулоцитами"
    if "cbc" in low or "blood_count" in low:
        return "Общеклинический анализ крови с лейкоцитарной формулой"
    if "biochemistry_blood" in low or ("biochemistry" in low and "blood" in low):
        return "Биохимия крови"
    if "lipid" in low:
        return "Липидный профиль"
    if "organic_acid" in low or "organic_acids" in low:
        return "Органические кислоты (моча)"
    if "aggregate_clinical_report" in low or "summary" in low or "aggregate" in low or "multi_doc" in low:
        return "Сводный клинический отчёт"
    if "generic_lab" in low:
        return "Лабораторный отчёт"
    return (document_type or "—").replace("_", " ")


def _report_subtitle_for_type(document_type: str) -> str:
    """Заголовок отчёта по типу документа. biochemistry_blood / lipid_panel — биохимия крови."""
    low = (document_type or "").lower()
    if "biochemistry_blood" in low or "biochemistry" in low:
        return "Структурированная интерпретация биохимического анализа крови"
    if "cbc_with_reticulocytes" in low or "cbc_with_retic" in low:
        return "Структурированная интерпретация общеклинического анализа крови с лейкоцитарной формулой и ретикулоцитами"
    if "cbc" in low:
        return "Структурированная интерпретация общеклинического анализа крови с лейкоцитарной формулой"
    if "organic_acids" in low or "organic_acid" in low:
        return "Структурированная интерпретация профиля органических кислот"
    if "lipid" in low:
        return "Структурированная интерпретация биохимического анализа крови"
    return "Структурированная интерпретация лабораторного исследования"


def _merged_document_meta(data: Dict[str, Any]) -> Dict[str, Any]:
    """document_summary + patient: пол, возраст, биоматериал, даты (из бланка / профиля)."""
    ds = dict(data.get("document_summary") or {})
    pat = data.get("patient") if isinstance(data.get("patient"), dict) else {}
    for k, v in pat.items():
        if v is None:
            continue
        sv = str(v).strip()
        if not sv or sv == "—":
            continue
        ds[k] = v
    return ds


def _format_age_display(raw: Any) -> str:
    if raw is None or raw == "":
        return "—"
    try:
        n = int(float(raw))
        return f"{n} лет"
    except (TypeError, ValueError):
        return str(raw).strip() or "—"


def _render_header_table(data: Dict[str, Any]) -> str:
    doc = _merged_document_meta(data)
    raw_type = str(doc.get("doc_type") or data.get("doc_type") or data.get("document_type") or "").strip()
    filename = _s(data.get("document_name") or doc.get("document_name") or doc.get("filename") or "")
    type_friendly = _friendly_doc_type_label(raw_type, data) if raw_type else "—"
    age_cell = doc.get("age_years")
    if age_cell is None and doc.get("birth_year") is not None:
        try:
            age_cell = date.today().year - int(doc["birth_year"])
        except (TypeError, ValueError):
            age_cell = None
    age_str = _format_age_display(age_cell) if age_cell is not None else "—"
    patient_name = _s(doc.get("display_name") or doc.get("patient_name") or "")
    rows = [
        ("Документ (файл)", filename or "—"),
        ("Тип анализа", type_friendly),
    ]
    if patient_name:
        rows.append(("Пациент", patient_name))
    rows.extend(
        [
        ("Пол", doc.get("sex") or "—"),
        ("Возраст", age_str),
        ("Биоматериал", doc.get("sample_type") or "—"),
        ("Дата взятия", doc.get("collection_date") or "—"),
        ("Дата выполнения", doc.get("report_date") or "—"),
        ]
    )
    body = "".join(
        f"<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>"
        for k, v in rows
    )
    return f"""
    <table class="meta-table">
      <tbody>{body}</tbody>
    </table>
    """


def _render_summary_block(summary: Iterable[Any], data: Dict[str, Any] | None = None) -> str:
    vals = [_s(x) for x in summary if _s(x)]
    if not vals:
        if data and data.get("clinical_content_unavailable"):
            vals = ["—"]
        else:
            vals = ["Нет краткого вывода."]
    body = "".join(f"<li>{_esc(v)}</li>" for v in vals[:5])
    return f"""
    <div class="section-title">Краткий вывод</div>
    <div class="section-body">
      <ul class="plain-list">{body}</ul>
    </div>
    """


def _empty_abnormal_message(doc_type: str) -> str:
    low = (doc_type or "").lower()
    if "cbc" in low:
        return "Данных за анемию, выраженный воспалительный сдвиг или тромбоцитопению не получено. Пограничные или мягкие изменения см. в кратком выводе."
    return "Нет значимых отклонений."


def _render_abnormal_table(rows: List[Dict[str, Any]], data: Dict[str, Any] | None = None) -> str:
    doc_type = str((data or {}).get("doc_type") or (data or {}).get("document_type") or "")
    if not rows:
        if data and data.get("clinical_content_unavailable"):
            msg = "—"
        else:
            msg = _empty_abnormal_message(doc_type)
        return f"""
        <div class="section-title">Ключевые отклонения</div>
        <div class="section-body muted">{_esc(msg)}</div>
        """

    body = ""
    for row in rows[:12]:
        name = _s(row.get("name") or row.get("marker"))
        cat = _s(row.get("category"))
        value = _s(row.get("value"))
        ref = f"{_s(row.get('ref_low'))}–{_s(row.get('ref_high'))}"
        flag = _s(row.get("flag") or row.get("direction"))
        symbol = _flag_symbol(flag)
        label = _flag_label(flag)
        comment = _s(row.get("comment") or "—")

        body += f"""
        <tr>
          <td class="col-name">{_esc(name)}</td>
          <td>{_esc(cat)}</td>
          <td class="col-value">{_esc(value)}</td>
          <td>{_esc(ref)}</td>
          <td class="col-flag">{_esc(symbol)} {_esc(label)}</td>
          <td>{_esc(comment)}</td>
        </tr>
        """

    return f"""
    <div class="section-title">Ключевые отклонения</div>
    <div class="section-body">
      <table class="report-table">
        <thead>
          <tr>
            <th>Показатель</th>
            <th>Группа</th>
            <th>Результат</th>
            <th>Референс</th>
            <th>Оценка</th>
            <th>Комментарий</th>
          </tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </div>
    """


def _empty_grouped_message(doc_type: str) -> str:
    low = (doc_type or "").lower()
    if "cbc" in low:
        return "Признаков анемии, выраженного лейкоцитарного сдвига или тромбоцитопении не выявлено. Оценка по группам см. в кратком выводе."
    if "lipid" in low:
        return (
            "Числовые значения липидов из текста не извлечены (или бланк без явных ОХ/ЛПНП/ЛПВП/ТГ) — "
            "таблица по группам не сформирована. При корректном PDF повторите загрузку; окончательная оценка — врачом."
        )
    return "Нет групп для интерпретации."


def _render_group_table(rows: List[Dict[str, Any]], data: Dict[str, Any] | None = None) -> str:
    doc_type = str((data or {}).get("doc_type") or (data or {}).get("document_type") or "")
    if not rows:
        if data and data.get("clinical_content_unavailable"):
            msg = "—"
        else:
            msg = _empty_grouped_message(doc_type)
        return f"""
        <div class="section-title">Клиническая интерпретация по группам</div>
        <div class="section-body muted">{_esc(msg)}</div>
        """

    body = ""
    for row in rows[:8]:
        group = _s(row.get("group"))
        interp = _s(row.get("interpretation"))
        body += f"""
        <tr>
          <td class="col-name">{_esc(group)}</td>
          <td>{_esc(interp)}</td>
        </tr>
        """

    return f"""
    <div class="section-title">Клиническая интерпретация по группам</div>
    <div class="section-body">
      <table class="report-table">
        <thead>
          <tr>
            <th>Группа</th>
            <th>Интерпретация</th>
          </tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </div>
    """


def _empty_hypotheses_message(doc_type: str) -> str:
    low = (doc_type or "").lower()
    if "cbc" in low:
        return "Убедительных лабораторных паттернов за анемию, лейкоцитарный сдвиг или тромбоцитопению не выявлено. Обнаружены неспецифические пограничные изменения — требуют оценки в контексте жалоб."
    return "Существенных патологических паттернов не выявлено."


def _hypotheses_fallback_from_clinical_patterns(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Если lipid_engine очистил гипотезы, но есть P1/P2 — не показываем пустой блок «паттернов нет»."""
    cp = data.get("clinical_patterns") or []
    out: List[Dict[str, Any]] = []
    for raw in cp[:8]:
        if not isinstance(raw, dict):
            continue
        label = _s(raw.get("label") or raw.get("code"))
        if not label:
            continue
        rationale = _s(raw.get("rationale") or "")
        lvl = _s(raw.get("level") or "")
        code = _s(raw.get("code") or "")
        h = f"{label}" + (f" ({lvl})" if lvl else "")
        out.append(
            {
                "hypothesis": h,
                "basis": code,
                "comment": rationale or "Рабочая интерпретация по совокупности маркеров, не диагноз.",
            }
        )
    return out


def _render_hypotheses(rows: List[Dict[str, Any]], data: Dict[str, Any] | None = None) -> str:
    doc_type = str((data or {}).get("doc_type") or (data or {}).get("document_type") or "")
    if not rows and data and not data.get("clinical_content_unavailable"):
        rows = _hypotheses_fallback_from_clinical_patterns(data)
    if not rows:
        if data and data.get("clinical_content_unavailable"):
            msg = "—"
        else:
            msg = _empty_hypotheses_message(doc_type)
        return f"""
        <div class="section-title">Рабочие гипотезы</div>
        <div class="section-body muted">{_esc(msg)}</div>
        """

    body = ""
    for row in rows[:5]:
        h = _s(row.get("hypothesis"))
        c = _s(row.get("comment") or "Это рабочая гипотеза, а не диагноз.")
        basis = _s(row.get("basis"))
        conf = _s(row.get("confidence"))

        extra = []
        if basis:
            extra.append(f"Основание: {basis}")
        if conf:
            extra.append(f"Уверенность: {conf}")
        extra_text = " | ".join(extra)

        body += (
            "<li>"
            f"<b>{_esc(h)}</b>."
            + (f" <span class='muted'>{_esc(extra_text)}</span>" if extra_text else "")
            + f" {_esc(c)}"
            + "</li>"
        )

    return f"""
    <div class="section-title">Рабочие гипотезы</div>
    <div class="section-body">
      <ul class="plain-list">{body}</ul>
    </div>
    """


def _render_followup(rows: List[Dict[str, Any]], data: Dict[str, Any] | None = None) -> str:
    if not rows:
        placeholder = "—" if (data and data.get("clinical_content_unavailable")) else "Нет рекомендаций."
        return f"""
        <div class="section-title">Что проверить дальше</div>
        <div class="section-body muted">{_esc(placeholder)}</div>
        """

    body = ""
    for row in rows[:8]:
        direction = _s(row.get("direction"))
        check = _s(row.get("check"))
        why = _s(row.get("why"))
        pr = _s(row.get("priority"))
        body += f"""
        <tr>
          <td class="col-name">{_esc(direction)}</td>
          <td>{_esc(check)}</td>
          <td>{_esc(why)}</td>
          <td>{_esc(pr)}</td>
        </tr>
        """

    return f"""
    <div class="section-title">Что проверить дальше</div>
    <div class="section-body">
      <table class="report-table">
        <thead>
          <tr>
            <th>Направление</th>
            <th>Что проверить</th>
            <th>Зачем</th>
            <th>Приоритет</th>
          </tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </div>
    """


def _render_correction_directions(items: List[Any]) -> str:
    if not items:
        return ""
    note = (
        "Ниже приведены не назначения, а возможные направления обсуждения после очной клинической оценки."
    )
    first = items[0] if items else None
    if isinstance(first, dict) and (first.get("title") or first.get("what_it_means") or first.get("recommended")):
        parts = [f'<div class="section-note">{_esc(note)}</div>']
        for idx, block in enumerate(items[:12]):
            if not isinstance(block, dict):
                continue
            title = _s(block.get("title"))
            what = _s(block.get("what_it_means"))
            rec_list = block.get("recommended") or []
            if not title and not what and not rec_list:
                continue
            if title:
                parts.append(
                    f'<div class="block-title" style="margin-top:{14 if idx else 6}px;font-weight:700;">{_esc(title)}</div>'
                )
            if what:
                parts.append(f'<p style="margin:4px 0 6px;"><strong>Что это значит:</strong> {_esc(what)}</p>')
            if rec_list:
                parts.append('<p style="margin:2px 0 4px;"><strong>Рекомендуется:</strong></p>')
                parts.append("<ul class=\"plain-list\">" + "".join(f"<li>{_esc(_s(x))}</li>" for x in rec_list[:8] if _s(x)) + "</ul>")
        parts.append(
            '<div class="block-title" style="margin-top:14px;font-weight:700;">Итог</div>'
            '<p style="margin:4px 0;">Основная логика коррекции: убрать лишнюю нагрузку → нормализовать питание → проверить дефициты → только потом добавки (по назначению врача).</p>'
            '<p class="muted" style="margin-top:8px;">Это не назначения. Интерпретация зависит от клинической картины.</p>'
        )
        return f"""
    <div class="section-title">Потенциальные направления коррекции</div>
    <div class="section-body">
      {"".join(parts)}
    </div>
    """

    vals = [_s(x) for x in items if _s(x)]
    body = "".join(f"<li>{_esc(v)}</li>" for v in vals[:10])
    return f"""
    <div class="section-title">Потенциальные направления коррекции</div>
    <div class="section-body">
      <div class="section-note">{_esc(note)}</div>
      <ul class="plain-list">{body}</ul>
    </div>
    """


def _render_recommendation_blocks(blocks: List[Dict[str, Any]]) -> str:
    """Шесть блоков «что делать»: убрать причину → митохондрии → глутатион → витамины → микробиом → допроверить."""
    if not blocks:
        return ""

    note = "Нормальные рекомендации по делу для обсуждения с врачом. Не назначение."
    parts = [f'<div class="section-note">{_esc(note)}</div>']

    for block in blocks[:6]:
        title = _s(block.get("title") or "")
        items = block.get("items") or []
        if not title:
            continue
        item_lines = "".join(f"<li>{_esc(x)}</li>" for x in items if _s(x))
        parts.append(
            f'<div class="block-title" style="margin-top:10px;font-weight:700;">{_esc(title)}</div>'
            f'<ul class="plain-list">{item_lines}</ul>'
        )

    return f"""
    <div class="section-title">Рекомендации по блокам (что делать)</div>
    <div class="section-body">
      {"".join(parts)}
    </div>
    """


def _render_limitations(rows: List[Any]) -> str:
    vals: List[str] = []
    for row in rows or []:
        if isinstance(row, dict):
            left = _s(row.get("limitation"))
            right = _s(row.get("value"))
            if left and right and right != "—":
                vals.append(f"{left}: {right}")
            elif left:
                vals.append(left)
        else:
            v = _s(row)
            if v:
                vals.append(v)

    if not vals:
        return ""

    body = "".join(f"<li>{_esc(v)}</li>" for v in vals[:10])

    return f"""
    <div class="section-title">Ограничения интерпретации</div>
    <div class="section-body">
      <ul class="plain-list">{body}</ul>
    </div>
    """


def _render_borderline_table(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return ""

    body = ""
    for row in rows[:10]:
        name = _s(row.get("name"))
        cat = _s(row.get("category"))
        value = _s(row.get("value"))
        ref = f"{_s(row.get('ref_low'))}–{_s(row.get('ref_high'))}"
        flag = _s(row.get("flag"))
        symbol = _flag_symbol(flag)
        label = _flag_label(flag)
        comment = _s(row.get("comment") or "—")

        body += f"""
        <tr>
          <td class="col-name">{_esc(name)}</td>
          <td>{_esc(cat)}</td>
          <td class="col-value">{_esc(value)}</td>
          <td>{_esc(ref)}</td>
          <td class="col-flag">{_esc(symbol)} {_esc(label)}</td>
          <td>{_esc(comment)}</td>
        </tr>
        """

    return f"""
    <div class="section-title">Пограничные значения</div>
    <div class="section-body">
      <table class="report-table">
        <thead>
          <tr>
            <th>Показатель</th>
            <th>Группа</th>
            <th>Результат</th>
            <th>Референс</th>
            <th>Оценка</th>
            <th>Комментарий</th>
          </tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </div>
    """


def _render_footer_note(data: Dict[str, Any] | None = None) -> str:
    if data and data.get("clinical_content_unavailable"):
        return """<div class="footer-note">—</div>"""
    return """
    <div class="footer-note">
      Результатов исследования недостаточно для постановки диагноза. Интерпретация должна выполняться врачом
      с учётом жалоб, анамнеза, лекарственного фона, питания и клинического контекста.
    </div>
    """


def _render_patient_friendly(blocks: Dict[str, Any]) -> str:
    """Блоки «Что происходит», «Что это значит», «Что делать» — понятная подача и действия."""
    if not blocks or not isinstance(blocks, dict):
        return ""
    parts = []
    for key, title in (
        ("what_happened", "Что происходит"),
        ("what_it_means", "Что это значит"),
        ("what_to_do", "Что делать"),
    ):
        items = blocks.get(key)
        if not items:
            continue
        if isinstance(items, str):
            items = [items]
        items = [str(x).strip() for x in items if str(x).strip()]
        if not items:
            continue
        parts.append(
            f'<div class="block-title" style="margin-top:12px;font-weight:700;">{_esc(title)}</div>'
            + "".join(f'<p style="margin:4px 0 6px;">{_esc(x)}</p>' for x in items)
        )
    important = _s(blocks.get("important"))
    if important:
        parts.append(
            f'<p class="muted" style="margin-top:10px;"><strong>Важно:</strong> {_esc(important)}</p>'
        )
    if not parts:
        return ""
    return f"""
    <div class="section-title">Понятно и по делу</div>
    <div class="section-body">
      {"".join(parts)}
    </div>
    """


def _render_upsell_cta(cta: Dict[str, Any]) -> str:
    """Блок призыва к действию: персональный план, следующий шаг."""
    if not cta or not cta.get("show"):
        return ""
    title = _s(cta.get("title"))
    desc = _s(cta.get("description"))
    label = _s(cta.get("cta_label")) or "Подробнее"
    link = _s(cta.get("cta_link")) or "#"
    if not title and not desc:
        return ""
    body = ""
    if title:
        body += f'<p style="font-weight:700;margin:0 0 8px;">{_esc(title)}</p>'
    if desc:
        body += f'<p style="margin:0 0 10px;">{_esc(desc)}</p>'
    body += f'<p style="margin:0;"><a href="{_esc(link)}" class="report-cta-link" style="display:inline-block;padding:8px 14px;background:#0f766e;color:#fff;text-decoration:none;border-radius:6px;font-weight:600;">{_esc(label)}</a></p>'
    return f"""
    <div class="section-title">Дальше</div>
    <div class="section-body" style="background:#f0fdfa;border-color:#0d9488;">
      {body}
    </div>
    """


def build_physician_report_html(data: Dict[str, Any]) -> str:
    doc_type = str(data.get("doc_type") or data.get("document_type") or "").lower()
    report_title = str(data.get("report_title") or REPORT_TITLE).strip()
    subtitle = str(data.get("report_subtitle") or _report_subtitle_for_type(doc_type)).strip()
    pm = _s(data.get("pattern_main_conclusion") or "")
    if pm:
        summary = [ln.strip() for ln in pm.split("\n") if ln.strip()] if "\n" in pm else [pm]
    else:
        summary = data.get("summary") or []
    abnormal = data.get("abnormal_markers_table") or data.get("abnormal_findings") or []
    grouped = data.get("grouped_interpretation_table") or []
    hypos = data.get("top_hypotheses_table") or []
    follow = data.get("recommended_followup_table") or []
    limitations = data.get("limitations") or []
    borderline = data.get("borderline_markers_table") or []
    correction_directions = data.get("possible_correction_directions") or []
    recommendation_blocks = data.get("recommendation_blocks") or []
    patient_friendly = data.get("patient_friendly") or {}
    upsell_cta = data.get("upsell_cta") or {}

    return f"""
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(report_title)}</title>
<style>
:root {{
  --bg: #ffffff;
  --text: #1f2937;
  --muted: #6b7280;
  --line: #d1d5db;
  --head: #eceff3;
  --head-dark: #dfe3e8;
}}
* {{
  box-sizing: border-box;
}}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 13px/1.45 Arial, Helvetica, sans-serif;
}}
.page {{
  width: 100%;
  max-width: 980px;
  margin: 0 auto;
  padding: 22px 24px 28px;
}}
.topbar {{
  border-bottom: 2px solid #bfc5cc;
  padding-bottom: 10px;
  margin-bottom: 14px;
}}
.report-title {{
  font-size: 24px;
  font-weight: 700;
  margin: 0 0 4px;
}}
.report-subtitle {{
  font-size: 12px;
  color: var(--muted);
  margin: 0;
}}
.meta-table {{
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 16px;
}}
.meta-table td {{
  border: 1px solid var(--line);
  padding: 7px 10px;
}}
.meta-table td:first-child {{
  width: 220px;
  background: var(--head);
  font-weight: 700;
}}
.section-title {{
  background: var(--head-dark);
  border: 1px solid var(--line);
  border-bottom: none;
  padding: 8px 10px;
  font-weight: 700;
  font-size: 14px;
  margin-top: 12px;
}}
.section-body {{
  border: 1px solid var(--line);
  padding: 10px 12px;
}}
.section-note {{
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--muted);
}}
.plain-list {{
  margin: 0;
  padding-left: 18px;
}}
.plain-list li {{
  margin: 0 0 8px;
}}
.report-table {{
  width: 100%;
  border-collapse: collapse;
}}
.report-table th,
.report-table td {{
  border: 1px solid var(--line);
  padding: 7px 8px;
  vertical-align: top;
  text-align: left;
}}
.report-table th {{
  background: var(--head);
  font-weight: 700;
}}
.col-name {{
  font-weight: 700;
}}
.col-value {{
  white-space: nowrap;
}}
.col-flag {{
  white-space: nowrap;
  font-weight: 700;
}}
.muted {{
  color: var(--muted);
}}
.footer-note {{
  margin-top: 18px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
  font-size: 12px;
  color: var(--muted);
}}
@media print {{
  .page {{
    max-width: none;
    padding: 0;
  }}
}}
</style>
</head>
<body>
  <div class="page">
    <div class="topbar">
      <div class="report-title">{_esc(report_title)}</div>
      <div class="report-subtitle">{_esc(subtitle)}</div>
    </div>

    {_render_header_table(data)}
    {_render_summary_block(summary, data)}
    {_render_abnormal_table(abnormal, data)}
    {_render_patient_friendly(patient_friendly)}
    {_render_group_table(grouped, data)}
    {_render_hypotheses(hypos, data)}
    {_render_followup(follow, data)}
    {_render_correction_directions(correction_directions)}
    {_render_recommendation_blocks(recommendation_blocks)}
    {_render_borderline_table(borderline)}
    {_render_limitations(limitations)}
    {_render_upsell_cta(upsell_cta)}
    {_render_footer_note(data)}
  </div>
</body>
</html>
""".strip()
