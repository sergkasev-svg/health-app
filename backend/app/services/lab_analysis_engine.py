"""
LabAnalysisEngine: обёртка над анализом документов (анализы крови, дневник питания, данные активности).
Структурированный вывод: отклонения (анемия, кортизол и т.д.), нутрицевтические показатели, активность.
Изолированный модуль. Использует существующий document_analysis.
"""
from typing import Any

from app.services.document_analysis import analyze_document_text


def analyze_lab_text(text: str) -> dict[str, Any]:
    """
    Парсинг и нормализация медицинских/нутрициологических/активности данных из текста.
    Возвращает структуру для структурированного отчёта голосового консьержа.
    """
    raw = analyze_document_text(text)
    conclusions = raw.get("conclusions") or []
    treatment = raw.get("treatment") or []
    nutrition = raw.get("nutrition") or []
    activity = raw.get("activity") or []
    diagnosis_hints = raw.get("diagnosis_hints") or []

    # Отклонения по данным анализов
    deviations = list(conclusions)
    for h in diagnosis_hints:
        if h and h.strip() and h.strip() not in deviations:
            deviations.append(h.strip())

    # Нутрицевтические маркеры (железо, D, B12, магний и т.д.)
    nutrition_markers = []
    text_lower = (text or "").lower()
    for n in nutrition:
        if n and n.strip():
            nutrition_markers.append(n.strip())
    if any(k in text_lower for k in ["ферритин", "железо", "гемоглобин", "оак"]):
        nutrition_markers.append("Оценка железа и гемоглобина по анализам")
    if any(k in text_lower for k in ["витамин d", "25-oh", "25 oh"]):
        nutrition_markers.append("Витамин D по анализам")
    if any(k in text_lower for k in ["b12", "кобаламин", "витамин b12"]):
        nutrition_markers.append("B12 по анализам")

    # Активность: переутомление, шаги, нагрузка
    activity_notes = list(activity)
    if any(k in text_lower for k in ["шаг", "steps", "трениров", "нагрузк", "overtraining", "переутомлен"]):
        activity_notes.append("Учёт данных об активности и восстановлении")

    return {
        "deviations": deviations[:15],
        "treatment": treatment[:20],
        "nutrition_markers": nutrition_markers[:15],
        "nutrition_recommendations": nutrition[:15],
        "activity_recommendations": activity_notes[:15],
        "severity": raw.get("severity") or "GREEN",
        "conclusions": conclusions,
        "diagnosis_hints": diagnosis_hints,
    }
