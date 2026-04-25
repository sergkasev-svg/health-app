"""
Форматирование врачебного отчёта в читаемый текст для экспорта/показа врачу.
"""
from __future__ import annotations

from app.services.physician_report_models import PhysicianReport


def format_physician_report(report: PhysicianReport) -> str:
    """
    Текстовый отчёт: Жалобы, Анамнез, Анализы, Оценка, Дифференциальный ряд, План, Красные флаги.
    """
    if not report:
        return ""

    parts: list[str] = []

    if report.patient_info and (report.patient_info.age is not None or report.patient_info.sex):
        parts.append("Пациент:")
        if report.patient_info.age is not None:
            parts.append(f"  Возраст: {report.patient_info.age}")
        if report.patient_info.sex:
            parts.append(f"  Пол: {report.patient_info.sex}")
        parts.append("")

    parts.append("Жалобы:")
    if report.symptoms.key_symptoms:
        for s in report.symptoms.key_symptoms:
            parts.append(f"  - {s}")
    else:
        parts.append("  - не указаны")
    if report.symptoms.duration:
        parts.append(f"  Длительность: {report.symptoms.duration}")
    if report.symptoms.progression:
        parts.append(f"  Динамика: {report.symptoms.progression}")
    parts.append("")

    parts.append("Анамнез (кратко):")
    if report.symptoms.key_symptoms:
        parts.append(f"  - {', '.join(report.symptoms.key_symptoms)}")
    else:
        parts.append("  - нет данных")
    parts.append("")

    parts.append("Анализы:")
    if report.labs:
        for lab in report.labs:
            val_str = f"{lab.value}" if lab.value is not None else "—"
            unit_str = f" {lab.unit}" if lab.unit else ""
            flag_str = f" ({lab.flag})" if lab.flag and lab.flag != "normal" else ""
            interp = f"  → {lab.interpretation}" if lab.interpretation else ""
            parts.append(f"  - {lab.marker}: {val_str}{unit_str}{flag_str}{interp}")
    else:
        parts.append("  - нет данных")
    parts.append("")

    parts.append("Оценка:")
    if report.assessment.main_hypotheses:
        for h in report.assessment.main_hypotheses:
            parts.append(f"  - {h}")
    else:
        parts.append("  - данных недостаточно для выводов")
    if report.assessment.supporting_evidence:
        for e in report.assessment.supporting_evidence:
            parts.append(f"  - {e}")
    parts.append("")

    if report.assessment.differential:
        parts.append("Дифференциальный ряд:")
        for d in report.assessment.differential:
            parts.append(f"  - {d}")
        parts.append("")

    parts.append("План:")
    if report.plan.recommended_tests:
        for t in report.plan.recommended_tests:
            parts.append(f"  - {t}")
    if report.plan.referrals:
        for r in report.plan.referrals:
            parts.append(f"  - консультация: {r}")
    if report.plan.follow_up:
        parts.append(f"  - {report.plan.follow_up}")
    if not report.plan.recommended_tests and not report.plan.referrals and not report.plan.follow_up:
        parts.append("  - по результатам очного осмотра")
    parts.append("")

    if report.red_flags:
        parts.append("Красные флаги:")
        for f in report.red_flags:
            parts.append(f"  - {f}")
        parts.append("")

    if report.notes:
        parts.append("Примечания:")
        parts.append(f"  {report.notes}")

    return "\n".join(parts).strip()
