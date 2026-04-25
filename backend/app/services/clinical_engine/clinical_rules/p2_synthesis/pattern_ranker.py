"""
Ранжирование клинических паттернов: значимость, доказательства, риск, педиатрия, main_for_summary.
"""
from __future__ import annotations

from typing import Any, List, Optional

from app.services.clinical_engine.contracts import ClinicalPattern

# =========================
# Configuration
# =========================

LEVEL_WEIGHT = {
    "P1": 100,
    "P2": 40,
}

CATEGORY_BASE_WEIGHT = {
    "hematology": 15,
    "lipid": 14,
    "glucose": 12,
    "urinary": 10,
    "vitamin": 6,
    "inflammation": 5,
    "liver": 9,
    "kidney": 11,
    "other": 0,
}

RISK_DOMAIN_TO_CATEGORY = {
    "hematology": ["hematology"],
    "cardiometabolic": ["lipid", "glucose", "vitamin"],
    "urinary": ["urinary", "kidney"],
    "inflammation": ["inflammation"],
}

RISK_LEVEL_BONUS = {
    "low": 0,
    "moderate": 4,
    "high": 10,
    "urgent": 20,
}

MAX_MAIN_SUMMARY_PATTERNS = 2


# =========================
# Helpers
# =========================


def _norm(text: str | None) -> str:
    return " ".join((text or "").strip().split()).lower()


def _safe_category_weight(category: str) -> int:
    return CATEGORY_BASE_WEIGHT.get(_norm(category), CATEGORY_BASE_WEIGHT["other"])


def _evidence_bonus(evidence: List[str]) -> int:
    """Чем больше независимых опорных маркеров, тем выше вес."""
    n = len(set(evidence or []))
    if n >= 4:
        return 8
    if n == 3:
        return 6
    if n == 2:
        return 3
    if n == 1:
        return 1
    return 0


def _confidence_bonus(confidence: float) -> int:
    if confidence >= 0.95:
        return 8
    if confidence >= 0.90:
        return 6
    if confidence >= 0.80:
        return 4
    if confidence >= 0.70:
        return 2
    return 0


def _risk_bonus_for_pattern(pattern: ClinicalPattern, risks: List[Any]) -> int:
    total = 0
    pcat = _norm(pattern.category)

    for risk in risks or []:
        related_categories = RISK_DOMAIN_TO_CATEGORY.get(_norm(getattr(risk, "domain", None)), [])
        if pcat in related_categories:
            total += RISK_LEVEL_BONUS.get(_norm(getattr(risk, "level", None)), 0)

            drivers_raw = getattr(risk, "drivers", None) or []
            drivers = [_norm(x) for x in drivers_raw]
            if _norm(pattern.code) in drivers:
                total += 6

    return total


def _pediatric_adjustment(pattern: ClinicalPattern, patient_age: Optional[int]) -> int:
    """
    Мягкая коррекция для детей/подростков:
    железо, глюкоза, витамин D, CBC-паттерны чуть выше;
    adult-style липиды без доп. логики не раздуваем.
    """
    if patient_age is None or patient_age >= 18:
        return 0

    category = _norm(pattern.category)
    code = _norm(pattern.code)

    if category in {"hematology", "glucose", "vitamin"}:
        return 5

    if "iron" in code or "deficiency" in code:
        return 6

    if category == "lipid":
        return 2

    return 0


def _compute_rank_score(
    pattern: ClinicalPattern,
    risks: List[RiskAssessment],
    patient_age: Optional[int],
) -> int:
    score = 0
    score += LEVEL_WEIGHT.get(_norm(pattern.level).upper(), 0)
    score += int(pattern.priority_score or 0)
    score += _safe_category_weight(pattern.category)
    score += _evidence_bonus(list(pattern.evidence or []))
    score += _confidence_bonus(float(pattern.confidence or 0.0))
    score += _risk_bonus_for_pattern(pattern, risks)
    score += _pediatric_adjustment(pattern, patient_age)
    return score


# =========================
# Main ranker
# =========================


def rank_patterns(
    patterns: List[ClinicalPattern],
    risks: List[Any] | None = None,
    patient_age: Optional[int] = None,
) -> List[ClinicalPattern]:
    """
    Возвращает новый отсортированный список паттернов.
    Выставляет main_for_summary для первых 1–2 паттернов уровня P1 (по итоговому рангу).
    """
    if not patterns:
        return []

    risks = risks or []

    scored: list[tuple[int, ClinicalPattern]] = []
    for p in patterns:
        score = _compute_rank_score(p, risks, patient_age)
        scored.append((score, p))

    scored.sort(
        key=lambda item: (
            -item[0],
            0 if _norm(item[1].level) == "p1" else 1,
            -float(item[1].confidence or 0.0),
            (item[1].label or "").lower(),
        )
    )

    ranked_patterns: List[ClinicalPattern] = []
    p1_main_count = 0
    for _, pattern in scored:
        is_main = False
        if _norm(pattern.level) == "p1" and p1_main_count < MAX_MAIN_SUMMARY_PATTERNS:
            is_main = True
            p1_main_count += 1
        ranked_patterns.append(pattern.model_copy(update={"main_for_summary": is_main}))

    return ranked_patterns


# =========================
# Convenience splitters
# =========================


def get_main_patterns(patterns: List[ClinicalPattern]) -> List[ClinicalPattern]:
    return [p for p in patterns if p.main_for_summary]


def get_secondary_patterns(patterns: List[ClinicalPattern]) -> List[ClinicalPattern]:
    return [p for p in patterns if not p.main_for_summary]


def split_patterns(
    patterns: List[ClinicalPattern],
) -> tuple[List[ClinicalPattern], List[ClinicalPattern]]:
    return get_main_patterns(patterns), get_secondary_patterns(patterns)
