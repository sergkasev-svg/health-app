"""
Поиск по офлайн-базам (лекарства, медицинский справочник).
Используется когда ИИ недоступен или как дополнение к ответу.
Возвращает профессиональный текст (для отчётов, врача) и простой (для голоса и пользователя).
"""
import json
import re
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_DATA_DIR = _SCRIPT_DIR.parent.parent.parent / "frontend" / "public" / "data"
_STOPWORDS = {
    "и",
    "в",
    "во",
    "на",
    "с",
    "со",
    "к",
    "по",
    "за",
    "от",
    "до",
    "у",
    "о",
    "об",
    "что",
    "как",
    "где",
    "когда",
    "почему",
    "мне",
    "меня",
    "мой",
    "моя",
    "моё",
    "мои",
    "это",
    "вот",
    "или",
    "а",
    "но",
    "же",
    "ли",
    "бы",
    "очень",
    "сильно",
    "просто",
    "делать",
    "делаю",
    "нужно",
    "надо",
}


def _load_json(name: str) -> dict:
    path = _DATA_DIR / name
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _normalize_query(q: str) -> list[str]:
    if not q or not q.strip():
        return []
    s = re.sub(r"[^\w\sа-яёa-z0-9]", " ", q.strip().lower())
    return [w for w in s.split() if len(w) >= 3 and w not in _STOPWORDS]


def _search_raw(user_message: str, max_med: int = 3, max_guide: int = 3) -> list[dict]:
    """Ищет по офлайн-базам. При длинном сообщении (описание жалоб) приоритет у справочника, не у лекарств."""
    words = _normalize_query(user_message)
    if not words:
        return []

    # Длинное описание состояния — приоритет справочнику (симптомы, первая помощь), меньше лекарств
    is_long_complaint = len(words) >= 5 or len((user_message or "").strip()) > 80
    if is_long_complaint:
        max_guide = min(5, max_guide + 2)
        max_med = min(2, max_med)

    parts: list[dict] = []
    guide_data = _load_json("medical_guide.json")
    med_data = _load_json("medications.json")
    min_hits = 2 if is_long_complaint else 1
    has_child_context = any(k in (user_message or "").lower() for k in ["ребен", "ребён", "ребенк", "ребёнк", "дит", "малыш", "child", "kids"])

    def _hits_count(text: str) -> int:
        text = (text or "").lower()
        return sum(1 for w in set(words) if w in text)

    def add_guide() -> None:
        for it in guide_data.get("items") or []:
            if sum(1 for p in parts if p.get("type") == "guide") >= max_guide:
                return
            title_l = str(it.get("title") or "").lower()
            category_l = str(it.get("category") or "").lower()
            if not has_child_context and ("реб" in title_l or "дет" in category_l):
                continue
            text = " ".join([
                str(it.get("title") or ""),
                str(it.get("category") or ""),
                str(it.get("summary") or ""),
                str(it.get("first_aid") or ""),
                str(it.get("when_to_doctor") or ""),
                str(it.get("simple_summary") or ""),
                str(it.get("diagnosis_hints") or ""),
                str(it.get("treatment_methods") or ""),
            ]).lower()
            title_text = " ".join([str(it.get("title") or ""), str(it.get("category") or "")]).lower()
            hits = _hits_count(text)
            title_hits = _hits_count(title_text)
            if hits >= min_hits or title_hits >= 1:
                score = hits * 2 + title_hits
                parts.append({
                    "type": "guide",
                    "title": it.get("title"),
                    "category": it.get("category"),
                    "summary": it.get("summary"),
                    "simple_summary": it.get("simple_summary"),
                    "first_aid": it.get("first_aid"),
                    "when_to_doctor": it.get("when_to_doctor"),
                    "urgent": it.get("urgent"),
                    "diagnosis_hints": it.get("diagnosis_hints"),
                    "treatment_methods": it.get("treatment_methods"),
                    "professional_note": it.get("professional_note"),
                    "_score": score,
                })

    def add_med() -> None:
        for it in med_data.get("items") or []:
            if sum(1 for p in parts if p.get("type") == "med") >= max_med:
                return
            text = " ".join([
                str(it.get("name") or ""),
                str(it.get("name_en") or ""),
                str(it.get("category") or ""),
                str(it.get("description") or ""),
                str(it.get("usage") or ""),
            ]).lower()
            name_text = " ".join([str(it.get("name") or ""), str(it.get("name_en") or "")]).lower()
            hits = _hits_count(text)
            name_hits = _hits_count(name_text)
            if hits >= min_hits or name_hits >= 1:
                score = hits * 2 + name_hits
                parts.append({
                    "type": "med",
                    "name": it.get("name"),
                    "category": it.get("category"),
                    "description": it.get("description"),
                    "usage": it.get("usage"),
                    "simple_usage": it.get("simple_usage"),
                    "contraindications": it.get("contraindications"),
                    "note": it.get("note"),
                    "_score": score,
                })

    # При описании жалоб сначала справочник (симптомы/первая помощь), потом лекарства
    if is_long_complaint:
        add_guide()
        add_med()
    else:
        add_med()
        add_guide()

    # Оставляем только самые релевантные: сортируем по _score и берём топ по каждому типу
    def by_score(p: dict) -> int:
        return int(p.get("_score") or 0)

    guide_parts = sorted([p for p in parts if p.get("type") == "guide"], key=by_score, reverse=True)
    med_parts = sorted([p for p in parts if p.get("type") == "med"], key=by_score, reverse=True)
    guide_top = guide_parts[:max_guide]
    med_top = med_parts[:max_med]
    for p in guide_top + med_top:
        p.pop("_score", None)
    # Порядок: сначала лучшие по справочнику, потом лекарства (для длинных жалоб уже так и было)
    if is_long_complaint:
        return guide_top + med_top
    return med_top + guide_top


def _format_professional(parts: list[dict]) -> str:
    """Форматирует найденные записи для профессионального отчёта и полноценных отчётов врачу."""
    if not parts:
        return ""
    lines = ["По офлайн-справочнику (для ознакомления, не заменяет консультацию врача):"]
    for p in parts:
        if p.get("type") == "med":
            lines.append("")
            lines.append("Лекарство: " + (p.get("name") or ""))
            if p.get("category"):
                lines.append("Категория: " + str(p["category"]))
            if p.get("description"):
                lines.append("Описание: " + str(p["description"]))
            if p.get("usage"):
                lines.append("Применение: " + str(p["usage"]))
            if p.get("contraindications"):
                lines.append("Противопоказания: " + str(p["contraindications"]))
            if p.get("note"):
                lines.append("Важно: " + str(p["note"]))
        else:
            lines.append("")
            lines.append("Тема: " + (p.get("title") or ""))
            if p.get("summary"):
                lines.append("Кратко: " + str(p["summary"]))
            if p.get("first_aid"):
                lines.append("Первая помощь: " + str(p["first_aid"]))
            if p.get("when_to_doctor"):
                lines.append("Когда к врачу: " + str(p["when_to_doctor"]))
            if p.get("urgent"):
                lines.append("Срочно (103): " + str(p["urgent"]))
            if p.get("diagnosis_hints"):
                lines.append("Дифференциальная диагностика: " + str(p["diagnosis_hints"]))
            if p.get("treatment_methods"):
                lines.append("Методы лечения: " + str(p["treatment_methods"]))
            if p.get("professional_note"):
                lines.append("Примечание: " + str(p["professional_note"]))
    return "\n".join(lines).strip()


def _format_simple(parts: list[dict]) -> str:
    """Форматирует короткий ответ простым языком для голоса и отчёта пользователю.
    Использует только один лучший блок из справочника (первый после сортировки по релевантности),
    чтобы не смешивать нерелевантные темы (например, порез и боль в животе)."""
    if not parts:
        return ""
    bits = []
    guide_parts = [p for p in parts if p.get("type") == "guide"]
    med_parts = [p for p in parts if p.get("type") == "med"]
    for p in med_parts[:2]:
        simple = p.get("simple_usage") or p.get("usage") or p.get("description")
        if simple:
            bits.append((p.get("name") or "Препарат") + ": " + str(simple))
    if guide_parts:
        p = guide_parts[0]
        simple = p.get("simple_summary") or p.get("summary")
        if simple:
            bits.append((p.get("title") or "Тема") + ". " + str(simple))
    if not bits:
        return _format_professional(parts)
    return " Кратко по справочнику: " + " ".join(bits)[:800]


def search_offline(user_message: str, max_med: int = 3, max_guide: int = 3) -> str:
    """
    Ищет по офлайн-базам и возвращает профессиональный текстовый ответ для вставки в чат.
    """
    parts = _search_raw(user_message, max_med=max_med, max_guide=max_guide)
    return _format_professional(parts)


def search_offline_with_formats(
    user_message: str, max_med: int = 3, max_guide: int = 3
) -> dict[str, str]:
    """
    Ищет по офлайн-базам и возвращает оба формата:
    - professional: для отчёта врачу и отображения в чате;
    - simple: простым языком для голосового ответа (TTS) и отчёта пользователю.
    """
    parts = _search_raw(user_message, max_med=max_med, max_guide=max_guide)
    return {
        "professional": _format_professional(parts),
        "simple": _format_simple(parts),
    }
