"""
Рендер отчёта для пациента: спокойный язык, без «диагнозов по гипотезе», без пугающих лейбов.
Строится из ClinicalCoreResult; при наличии clinical_patterns — смысл задают коды паттернов, не врачебные названия.
"""
from __future__ import annotations

import html
from typing import Any, Dict, List, Set

from app.services.clinical_engine.contracts import ClinicalCoreResult, ClinicalPattern
from app.services.clinical_engine.presentation.patient_safe_style import (
    patient_main_point_from_core,
    patient_next_step_line,
    patient_red_flags,
    patient_what_deviated_lines,
    patient_what_it_means,
)

# --- Простой язык по коду паттерна (не используем label с «железодефицитный паттерн» и т.п.) ---
PATTERN_PATIENT_LINES: Dict[str, Dict[str, Any]] = {
    "iron_deficiency_pattern": {
        "main": "показатели, связанные с запасами железа, выглядят сниженными",
        "attention": "Железо: есть признаки, что его запас может быть снижен — это стоит уточнить с врачом",
    },
    "low_hemoglobin_hematocrit_clarify_iron": {
        "main": "гемоглобин и гематокрит ниже референса — это нужно обсудить с врачом и при необходимости уточнить железо",
        "attention": "Общий анализ крови: снижение гемоглобина и гематокрита",
    },
    "vitamin_d_insufficiency": {
        "main": "уровень витамина D ниже желательного для обсуждения с врачом",
        "attention": "Витамин D: уровень ниже желательного",
    },
    "atherogenic_dyslipidemia": {
        "main": "есть изменения липидного профиля, которые стоит обсудить с врачом",
        "attention": "Липиды: есть изменения профиля холестерина — их нужно обсудить с врачом",
    },
    "glucose_metabolism_disorder": {
        "main": "есть сигналы, что углеводный обмен стоит уточнить с врачом",
        "attention": "Глюкоза и обмен углеводов — требует обсуждения с врачом",
    },
    "insulin_resistance_pattern": {
        "main": "есть показатели, по которым врач может оценить чувствительность к инсулину",
        "attention": "Обмен углеводов — обсудить с врачом",
    },
    "no_strong_inflammatory_signal": {
        "calm": "явных признаков сильного воспаления по этим показателям не видно",
    },
    "no_diabetic_signal": {
        "calm": "по этим данным не видно явного сахарного «тревожного» сигнала — уточняет врач",
    },
}

# Фразы врачебного отчёта, которые не копируем в действия (нижний регистр)
_FORBIDDEN_PATIENT_TERMS = (
    "железодефицитный паттерн",
    "атерогенная дислипидемия",
    "гиперлипопротеидемия",
    "дифференциальная диагностика",
)


def _norm_codes(patterns: List[ClinicalPattern]) -> Set[str]:
    return {p.code for p in patterns if getattr(p, "code", None)}


def _ordered_p1_patterns(patterns: List[ClinicalPattern]) -> List[ClinicalPattern]:
    ranked = sorted(
        patterns,
        key=lambda p: (
            0 if getattr(p, "main_for_summary", False) else 1,
            0 if (p.level or "").upper() == "P1" else 1,
            -int(p.priority_score or 0),
        ),
    )
    return [p for p in ranked if (p.level or "").upper() == "P1"]


def _build_main_and_attention_from_patterns(patterns: List[ClinicalPattern]) -> tuple[str, List[str]]:
    codes = _norm_codes(patterns)
    main_bits: List[str] = []
    attention: List[str] = []

    for p in _ordered_p1_patterns(patterns):
        block = PATTERN_PATIENT_LINES.get(p.code)
        if not block:
            continue
        if block.get("main"):
            main_bits.append(block["main"])
        if block.get("attention"):
            attention.append(block["attention"])

    if not main_bits:
        return "", []

    n = len(main_bits)
    if n == 1:
        head = "В анализе есть момент, который стоит обсудить с врачом:\n\n"
    else:
        head = f"В анализе есть {n} момента, которые стоит обсудить с врачом:\n\n"

    body = ";\n".join(f"— {m}" for m in main_bits) + "."

    tail = ""
    if "no_strong_inflammatory_signal" in codes:
        tail = (
            "\n\nОстальные показатели по этому анализу в целом не выглядят как признак острого воспаления "
            "или серьёзного сбоя — окончательно это оценивает врач."
        )

    main_text = head + body + tail
    return main_text.strip(), attention


def _calm_points_from_patterns(patterns: List[ClinicalPattern]) -> List[str]:
    out: List[str] = []
    codes = _norm_codes(patterns)
    for code, block in PATTERN_PATIENT_LINES.items():
        if code not in codes:
            continue
        calm = block.get("calm")
        if calm:
            out.append(calm)
    if out:
        out.append(
            "Критических отклонений, требующих экстренной помощи только по этому автоматическому отчёту, не видно — "
            "срочность определяет врач по симптомам."
        )
    return out


def _what_it_means_from_patterns(core: ClinicalCoreResult, codes: Set[str]) -> str:
    has_iron = "iron_deficiency_pattern" in codes
    has_d = "vitamin_d_insufficiency" in codes
    has_lipid = "atherogenic_dyslipidemia" in codes

    if has_iron and has_d:
        return (
            "Такая картина сама по себе не означает готовый диагноз, но говорит о том, что организму может не хватать "
            "железа и витамина D — это важно уточнить, особенно если есть слабость, утомляемость, бледность, "
            "снижение выносливости или другие жалобы на самочувствие."
        )
    if has_iron:
        return (
            "Снижение показателей, связанных с железом, само по себе не равно диагнозу: причины и план назначает врач. "
            "Если есть слабость, утомляемость или бледность — об этом стоит сказать на приёме."
        )
    if has_d:
        return (
            "Низкий уровень витамина D встречается часто; цели и коррекцию выбирают с врачом с учётом анализов и образа жизни."
        )
    if has_lipid:
        return (
            "Изменения липидного профиля не означают автоматически «болезнь по названию из отчёта»: их интерпретирует врач "
            "с учётом возраста, давления, семейного анамнеза и других факторов."
        )
    return patient_what_it_means(core)


def _actions_from_core(core: ClinicalCoreResult) -> List[str]:
    actions: List[str] = ["Показать анализ врачу"]
    seen = {a.lower() for a in actions}

    for line in list(core.pattern_next_steps_items or [])[:8]:
        t = (line or "").strip()
        if not t:
            continue
        low = t.lower()
        if any(bad in low for bad in _FORBIDDEN_PATIENT_TERMS):
            continue
        if t.lower() not in seen:
            seen.add(t.lower())
            actions.append(t)

    for s in core.next_steps or []:
        if isinstance(s, dict) and s.get("patient_visible") is False:
            continue
        if hasattr(s, "patient_visible") and getattr(s, "patient_visible", True) is False:
            continue
        line = patient_next_step_line(s if isinstance(s, dict) else s.__dict__ if hasattr(s, "__dict__") else {})
        if line and line.lower() not in seen:
            seen.add(line.lower())
            actions.append(line)

    actions.append("Не начинать лечение или добавки только по этому автоматическому отчёту — без обсуждения с врачом")

    # Уникальные, разумный лимит
    out: List[str] = []
    for a in actions:
        if a not in out:
            out.append(a)
    return out[:8]


DEFAULT_WHEN_NOT_TO_WAIT = [
    "Выраженная или нарастающая слабость",
    "Головокружение или обмороки",
    "Одышка в покое или при небольшой нагрузке",
    "Резкое ухудшение самочувствия",
    "Сильная боль в груди",
]


def _sanitize_line(text: str) -> str:
    s = (text or "").strip()
    low = s.lower()
    for bad in _FORBIDDEN_PATIENT_TERMS:
        if bad in low:
            return ""
    return s


def render_patient_safe_report(core: ClinicalCoreResult) -> Dict[str, Any]:
    """
    Возвращает мягкую версию отчёта и поля для API/UI.

    Секции:
    1. Что главное (main)
    2. Что требует внимания (attention)
    3. Что это может значить (what_it_means)
    4. Что сделать дальше (actions)
    5. Что по анализу выглядит спокойно (calm_points)
    6. Когда не ждать (when_not_to_wait)
    """
    patterns = list(core.clinical_patterns or [])
    codes = _norm_codes(patterns)

    if patterns and codes:
        main_text, attention = _build_main_and_attention_from_patterns(patterns)
        if not main_text:
            main_text = patient_main_point_from_core(core)
            attention = [_sanitize_line(x) for x in patient_what_deviated_lines(core) if _sanitize_line(x)]
        what_means = _what_it_means_from_patterns(core, codes)
        calm = _calm_points_from_patterns(patterns)
        if not calm and "no_strong_inflammatory_signal" not in codes:
            calm = [
                "По одному анализу редко можно судить обо всём сразу — врач сопоставит данные с самочувствием."
            ]
    else:
        main_text = patient_main_point_from_core(core)
        attention = [_sanitize_line(x) for x in patient_what_deviated_lines(core) if _sanitize_line(x)]
        if not attention:
            attention = ["Есть отклонения от референса — их стоит обсудить с врачом."]
        what_means = patient_what_it_means(core)
        calm = [
            "Если врач не говорил об срочности — ориентируйтесь на самочувствие и его рекомендации.",
        ]

    actions = _actions_from_core(core)
    when_not: List[str] = []
    legacy_red = patient_red_flags(core)
    if legacy_red and legacy_red[0] and len(legacy_red[0]) < 500:
        when_not.append(legacy_red[0])
    for x in DEFAULT_WHEN_NOT_TO_WAIT:
        if x not in when_not:
            when_not.append(x)

    # Плоский текст для совместимости и чтения
    parts: List[str] = [
        "Что главное",
        main_text,
        "",
        "Что требует внимания",
    ]
    for a in attention:
        parts.append(f"• {a}")
    parts.extend(["", "Что это может значить", what_means, "", "Что сделать дальше"])
    for ac in actions:
        parts.append(f"• {ac}")
    parts.extend(["", "Что по анализу выглядит спокойно"])
    for c in calm:
        parts.append(f"• {c}")
    parts.extend(["", "Когда не ждать"])
    for w in when_not[:8]:
        parts.append(f"• {w}")

    full_text = "\n".join(parts)

    structured = {
        "title": "Понятный отчёт",
        "sections": [
            {"id": "main", "title": "Что главное", "content": main_text},
            {"id": "attention", "title": "Что требует внимания", "items": attention},
            {"id": "what_it_means", "title": "Что это может значить", "content": what_means},
            {"id": "actions", "title": "Что сделать дальше", "items": actions},
            {"id": "calm", "title": "Что по анализу выглядит спокойно", "items": calm},
            {"id": "urgent", "title": "Когда не ждать", "items": when_not[:8]},
        ],
    }

    blocks: Dict[str, Any] = {
        "main": main_text,
        "attention": attention,
        "what_it_means": what_means,
        "actions": actions,
        "calm_points": calm,
        "when_not_to_wait": when_not[:8],
    }

    return {
        "title": structured["title"],
        "main": main_text,
        "main_point": main_text,
        "attention": attention,
        "what_it_means": what_means,
        "actions": actions,
        "calm_points": calm,
        "when_not_to_wait": when_not[:8],
        "next_steps_patient": actions,
        "red_flags": when_not[:8],
        "patient_report_text": full_text,
        "patient_report_structured": structured,
        "blocks": blocks,
        "patient_report_html": render_patient_safe_html(blocks),
    }


def render_patient_safe_html(blocks: Dict[str, Any]) -> str:
    """Простой HTML-карточки для экрана пациента (экранирование — через html.escape)."""
    esc = html.escape

    def card(title: str, body: str) -> str:
        return (
            f'<div class="card patient-safe-card">\n'
            f'  <div class="title">{esc(title)}</div>\n'
            f"  {body}\n"
            f"</div>\n"
        )

    chunks: List[str] = []
    main_raw = str(blocks.get("main") or "")
    main_html = "<br/>".join(esc(line) for line in main_raw.splitlines()) if main_raw else ""
    chunks.append(card("Что главное", f"<p>{main_html}</p>"))

    att = blocks.get("attention") or []
    if att:
        lis = "\n".join(f"    <li>{esc(x)}</li>" for x in att)
        chunks.append(card("Что требует внимания", f"<ul>\n{lis}\n  </ul>"))

    wim = blocks.get("what_it_means") or ""
    if wim:
        chunks.append(card("Что это может значить", f"<p>{esc(str(wim))}</p>"))

    act = blocks.get("actions") or []
    if act:
        lis = "\n".join(f"    <li>{esc(x)}</li>" for x in act)
        chunks.append(card("Что сделать дальше", f"<ul>\n{lis}\n  </ul>"))

    calm = blocks.get("calm_points") or []
    if calm:
        lis = "\n".join(f"    <li>{esc(x)}</li>" for x in calm)
        chunks.append(card("Что по анализу выглядит спокойно", f"<ul>\n{lis}\n  </ul>"))

    urgent = blocks.get("when_not_to_wait") or []
    if urgent:
        lis = "\n".join(f"    <li>{esc(x)}</li>" for x in urgent)
        chunks.append(card("Когда не ждать", f"<ul>\n{lis}\n  </ul>"))

    return "".join(chunks)


def patient_safe_report_to_example_json(report: Dict[str, Any]) -> Dict[str, Any]:
    """Узкий JSON для документации/фронта (без лишних полей)."""
    return {
        "title": report.get("title"),
        "blocks": report.get("blocks"),
        "structured": report.get("patient_report_structured"),
    }
