"""
Правила авто-детекции провальных кейсов: галлюцинации, плохой триаж, парсинг, слабый ответ, дубли вопросов, гейтинг.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.quality_models import FailureCase

# Мусорные диагнозы без поддержки контекстом
HALLUCINATION_TERMS = [
    "малярия", "сепсис", "импетиго", "лихорадка денге", "эбола", "менингококц",
    "дифтерия", "столбняк", "covid", "ковид", "sars-cov",
]


def _has_hallucination_in_list(items: List[str]) -> bool:
    if not items:
        return False
    lower = " ".join(str(x).lower() for x in items)
    return any(t in lower for t in HALLUCINATION_TERMS)


def detect_hallucination_failure(
    user_hypotheses: List[str],
    raw_context_summary: Dict[str, Any],
    event_id: str,
    timestamp: str,
    user_id: Optional[str],
    session_id: Optional[str],
) -> Optional[FailureCase]:
    """Если в user_hypotheses/physician report мусор (малярия, сепсис и т.д.) при CBC-only контексте — hallucination."""
    if not _has_hallucination_in_list(user_hypotheses):
        return None
    return FailureCase(
        case_id=f"hall_{event_id}",
        timestamp=timestamp,
        category="hallucination",
        severity="high",
        user_id=user_id,
        session_id=session_id,
        short_description="Мусорные/редкие диагнозы в гипотезах без поддержки контекстом.",
        raw_context_summary=raw_context_summary,
        resolution_status=None,
    )


def detect_bad_triage_failure(
    red_flags: List[str],
    state: str,
    urgency: str,
    event_id: str,
    timestamp: str,
    user_id: Optional[str],
    session_id: Optional[str],
) -> Optional[FailureCase]:
    """Red flags есть, а state не emergency/doctor_soon — bad_triage."""
    if not red_flags:
        return None
    if state in ("emergency", "doctor_soon"):
        return None
    severity = "critical" if red_flags else "high"
    return FailureCase(
        case_id=f"triage_{event_id}",
        timestamp=timestamp,
        category="bad_triage",
        severity=severity,
        user_id=user_id,
        session_id=session_id,
        short_description="Признаки красных флагов при state не emergency/doctor_soon.",
        raw_context_summary={"red_flags": red_flags, "state": state, "urgency": urgency},
        resolution_status=None,
    )


def detect_parsing_failure(
    had_uploaded_files: bool,
    file_types: List[str],
    lab_rows_count: int,
    physician_report_has_content: bool,
    event_id: str,
    timestamp: str,
    user_id: Optional[str],
    session_id: Optional[str],
) -> Optional[FailureCase]:
    """Файл загружен, но парсер вернул unknown/пустые rows и отчёт пустой — parsing_failure."""
    if not had_uploaded_files:
        return None
    if lab_rows_count > 0 and physician_report_has_content:
        return None
    if lab_rows_count > 0:
        return None
    return FailureCase(
        case_id=f"parse_{event_id}",
        timestamp=timestamp,
        category="parsing_failure",
        severity="medium",
        user_id=user_id,
        session_id=session_id,
        short_description="Загружен файл, но разбор пуст или неизвестный тип.",
        raw_context_summary={"file_types": file_types, "lab_rows_count": lab_rows_count},
        resolution_status=None,
    )


def detect_weak_answer_failure(
    state: str,
    final_message_len: int,
    has_questions: bool,
    has_care_plan: bool,
    has_report: bool,
    has_symptoms_or_labs: bool,
    event_id: str,
    timestamp: str,
    user_id: Optional[str],
    session_id: Optional[str],
) -> Optional[FailureCase]:
    """Слишком короткий/бесполезный ответ при непустом клиническом вводе."""
    if not has_symptoms_or_labs:
        return None
    if state == "needs_more_data" and has_questions:
        return None
    weak = final_message_len < 80 and not has_care_plan and not has_report
    if not weak:
        return None
    return FailureCase(
        case_id=f"weak_{event_id}",
        timestamp=timestamp,
        category="weak_answer",
        severity="medium",
        user_id=user_id,
        session_id=session_id,
        short_description="Короткий ответ без плана/отчёта при наличии ввода.",
        raw_context_summary={"state": state, "message_len": final_message_len},
        resolution_status=None,
    )


def detect_duplicate_questions_failure(
    questions_asked: List[str],
    memory_answered_questions: List[str],
    event_id: str,
    timestamp: str,
    user_id: Optional[str],
    session_id: Optional[str],
) -> Optional[FailureCase]:
    """Вопрос уже задавали и пользователь отвечал, но вопрос снова в списке — duplicate_questions."""
    if not questions_asked or not memory_answered_questions:
        return None
    answered_lower = {str(q).strip().lower() for q in memory_answered_questions}
    dupes = [q for q in questions_asked if str(q).strip().lower() in answered_lower]
    if not dupes:
        return None
    return FailureCase(
        case_id=f"dup_{event_id}",
        timestamp=timestamp,
        category="duplicate_questions",
        severity="low",
        user_id=user_id,
        session_id=session_id,
        short_description="Повторно заданы вопросы, на которые уже был ответ.",
        raw_context_summary={"duplicate_count": len(dupes)},
        resolution_status=None,
    )


def detect_gating_issue_failure(
    state: str,
    urgency: str,
    red_flags: List[str],
    physician_report_visible: bool,
    gated_physician_report: bool,
    event_id: str,
    timestamp: str,
    user_id: Optional[str],
    session_id: Optional[str],
) -> Optional[FailureCase]:
    """Критичная/safety информация скрыта гейтингом (emergency, но physician_report gated)."""
    if state != "emergency" and not red_flags:
        return None
    if physician_report_visible or not gated_physician_report:
        return None
    return FailureCase(
        case_id=f"gate_{event_id}",
        timestamp=timestamp,
        category="gating_issue",
        severity="critical",
        user_id=user_id,
        session_id=session_id,
        short_description="Safety-критичный контент скрыт гейтингом.",
        raw_context_summary={"state": state, "urgency": urgency},
        resolution_status=None,
    )
