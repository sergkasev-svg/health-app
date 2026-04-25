"""
Рендеринг структурированного медицинского отчёта в HTML.
Используется для physician report по документам (organic acids и др.).
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, List

CSS = """
:root {
  --bg: #f5f7fb;
  --card: #ffffff;
  --text: #1f2937;
  --muted: #6b7280;
  --border: #e5e7eb;
  --accent: #2563eb;
  --danger: #b91c1c;
  --warn: #b45309;
  --ok: #047857;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Inter, Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
}
.container {
  max-width: 1080px;
  margin: 32px auto;
  padding: 0 20px 40px;
}
.header {
  background: linear-gradient(135deg, #1d4ed8, #2563eb);
  color: white;
  padding: 24px 28px;
  border-radius: 18px;
  box-shadow: 0 10px 30px rgba(37, 99, 235, 0.18);
}
.header h1 { margin: 0 0 8px; font-size: 28px; }
.header p { margin: 0; opacity: 0.92; }
.grid {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 18px;
  margin-top: 20px;
}
.card {
  grid-column: span 12;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 20px 22px;
  box-shadow: 0 4px 18px rgba(15, 23, 42, 0.05);
}
.card.half { grid-column: span 6; }
@media (max-width: 900px) { .card.half { grid-column: span 12; } }
.section-title {
  margin: 0 0 14px;
  font-size: 18px;
  font-weight: 700;
}
.meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 18px;
}
.meta-item {
  padding: 12px 14px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid #eef2f7;
}
.label { color: var(--muted); font-size: 12px; margin-bottom: 4px; }
.value { font-size: 15px; font-weight: 600; }
.table {
  width: 100%;
  border-collapse: collapse;
  overflow: hidden;
  border-radius: 12px;
}
.table th, .table td {
  padding: 12px 10px;
  border-bottom: 1px solid var(--border);
  text-align: left;
  vertical-align: top;
  font-size: 14px;
}
.table th {
  color: var(--muted);
  font-weight: 700;
  background: #f8fafc;
}
.badge {
  display: inline-block;
  padding: 4px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}
.badge-high { background: #fee2e2; color: var(--danger); }
.badge-low { background: #fff7ed; color: var(--warn); }
.badge-normal { background: #dcfce7; color: var(--ok); }
.list {
  margin: 0;
  padding-left: 18px;
}
.list li { margin-bottom: 8px; line-height: 1.45; }
.footer-note {
  margin-top: 18px;
  color: var(--muted);
  font-size: 13px;
}
.code {
  background: #0f172a;
  color: #e2e8f0;
  padding: 14px;
  border-radius: 12px;
  font-size: 12px;
  overflow: auto;
}
"""


def _esc(x: Any) -> str:
    return html.escape("" if x is None else str(x))


def _badge(direction: str) -> str:
    direction = (direction or "").lower()
    if direction == "high":
        cls, label = "badge badge-high", "выше"
    elif direction == "low":
        cls, label = "badge badge-low", "ниже"
    else:
        cls, label = "badge badge-normal", "норма"
    return f'<span class="{cls}">{label}</span>'


def _render_meta(report: Dict[str, Any]) -> str:
    patient = report.get("patient", {})
    return f"""
    <div class="meta">
      <div class="meta-item"><div class="label">Тип документа</div><div class="value">{_esc(report.get('document_type', '—'))}</div></div>
      <div class="meta-item"><div class="label">Биоматериал</div><div class="value">{_esc(patient.get('sample_type', '—'))}</div></div>
      <div class="meta-item"><div class="label">Пол</div><div class="value">{_esc(patient.get('sex', '—'))}</div></div>
      <div class="meta-item"><div class="label">Возраст</div><div class="value">{_esc(patient.get('age_years', '—'))}</div></div>
      <div class="meta-item"><div class="label">Дата взятия</div><div class="value">{_esc(patient.get('collection_date', '—'))}</div></div>
      <div class="meta-item"><div class="label">Дата выполнения</div><div class="value">{_esc(patient.get('report_date', '—'))}</div></div>
    </div>
    """


def _render_findings(findings: List[Dict[str, Any]]) -> str:
    rows = []
    for item in findings:
        rows.append(
            "<tr>"
            f"<td><strong>{_esc(item.get('marker'))}</strong></td>"
            f"<td>{_esc(item.get('value'))}</td>"
            f"<td>{_esc(item.get('ref_low'))} – {_esc(item.get('ref_high'))}</td>"
            f"<td>{_esc(item.get('unit'))}</td>"
            f"<td>{_badge(item.get('direction'))}</td>"
            f"<td>{_esc(item.get('comment', ''))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="6">Нет отклонений для отображения</td></tr>')
    return (
        '<table class="table">'
        '<thead><tr><th>Показатель</th><th>Результат</th><th>Референс</th><th>Ед.</th><th>Оценка</th><th>Комментарий</th></tr></thead>'
        '<tbody>' + "".join(rows) + "</tbody></table>"
    )


def _render_list(items: List[str]) -> str:
    if not items:
        return '<div class="footer-note">Нет данных</div>'
    return "<ul class=\"list\">" + "".join(f"<li>{_esc(x)}</li>" for x in items) + "</ul>"


def render_report_html(report: Dict[str, Any]) -> str:
    """Рендерит структурированный отчёт в HTML."""
    title = report.get("title") or "Медицинский отчёт"
    summary = report.get("summary") or "Краткий структурированный отчёт по документу."
    interpretation = report.get("interpretation") or []
    follow_up = report.get("follow_up") or {}
    limitations = report.get("limitations") or []
    debug = report.get("debug") or {}

    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>{CSS}</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>{_esc(title)}</h1>
      <p>{_esc(summary)}</p>
    </div>

    <div class="grid">
      <section class="card">
        <h2 class="section-title">Документ и пациент</h2>
        {_render_meta(report)}
      </section>

      <section class="card">
        <h2 class="section-title">Ключевые отклонения</h2>
        {_render_findings(report.get('abnormal_findings') or [])}
      </section>

      <section class="card half">
        <h2 class="section-title">Краткая интерпретация</h2>
        {_render_list(interpretation)}
      </section>

      <section class="card half">
        <h2 class="section-title">Что проверить / к кому направить</h2>
        {_render_list((follow_up.get('tests') or []) + (follow_up.get('referrals') or []) + (follow_up.get('notes') or []))}
      </section>

      <section class="card">
        <h2 class="section-title">Ограничения интерпретации</h2>
        {_render_list(limitations)}
      </section>

      <section class="card">
        <h2 class="section-title">Технический блок</h2>
        <div class="code">{_esc(json.dumps(debug, ensure_ascii=False, indent=2))}</div>
        <div class="footer-note">Этот блок можно скрыть в пользовательском интерфейсе.</div>
      </section>
    </div>
  </div>
</body>
</html>
"""
