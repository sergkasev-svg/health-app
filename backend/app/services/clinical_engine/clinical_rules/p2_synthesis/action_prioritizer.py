"""
Приоритизация действий: clinical_patterns → связь с next_steps → risk → pediatric boost.
Работает с ClinicalPattern (Pydantic) и плоскими dict/next_steps из core.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class _PatternLike(Protocol):
    code: str
    label: str
    category: str
    level: str
    priority_score: int
    confidence: float
    rationale: str


@dataclass
class PrioritizedAction:
    domain: str
    what: str
    why: str
    base_priority: str
    final_priority: str
    score: int
    linked_patterns: List[str] = field(default_factory=list)


# =========================
# Priority maps
# =========================

BASE_PRIORITY_SCORE = {
    "low": 10,
    "medium": 20,
    "high": 30,
    "urgent": 40,
}

RISK_LEVEL_SCORE = {
    "low": 0,
    "moderate": 5,
    "high": 10,
    "urgent": 20,
}

FINAL_PRIORITY_BANDS = [
    (50, "urgent"),
    (35, "high"),
    (20, "medium"),
    (0, "low"),
]

PATTERN_DOMAIN_MAP = {
    "iron_deficiency_pattern": ["Железный обмен", "Гематология", "Общий анализ крови"],
    "atherogenic_dyslipidemia": ["Липидный обмен", "Кардиометаболический риск", "Эндокринология"],
    "vitamin_d_insufficiency": ["Витамины", "Витамин D", "Минеральный обмен"],
    "glucose_metabolism_disorder": ["Углеводный обмен", "Эндокринология"],
    "insulin_resistance_pattern": ["Углеводный обмен", "Эндокринология"],
    "possible_uti_pattern": ["Мочевые пути", "Урология"],
    "isolated_blood_reaction": ["Мочевые пути", "Урология"],
    "proteinuria_pattern": ["Почки", "Мочевые пути"],
    "inflammatory_pattern": ["Воспаление", "Инфекция"],
    "no_strong_inflammatory_signal": [],
    "no_diabetic_signal": [],
}


def _norm(text: str | None) -> str:
    return " ".join((text or "").strip().split())


@dataclass
class _NormStep:
    domain: str
    what: str
    why: str
    priority: str
    patient_visible: bool = True
    physician_visible: bool = True


def _normalize_step(s: Any) -> _NormStep:
    if isinstance(s, dict):
        return _NormStep(
            domain=str(s.get("domain") or s.get("direction") or "general"),
            what=str(s.get("what") or s.get("check") or "").strip(),
            why=str(s.get("why") or "").strip(),
            priority=str(s.get("priority") or "medium").lower(),
            patient_visible=s.get("patient_visible", True) is not False,
            physician_visible=s.get("physician_visible", True) is not False,
        )
    return _NormStep(
        domain=str(getattr(s, "domain", None) or getattr(s, "direction", None) or "general"),
        what=str(getattr(s, "what", None) or getattr(s, "check", None) or "").strip(),
        why=str(getattr(s, "why", "") or "").strip(),
        priority=str(getattr(s, "priority", "medium") or "medium").lower(),
        patient_visible=getattr(s, "patient_visible", True) is not False,
        physician_visible=getattr(s, "physician_visible", True) is not False,
    )


def _dedupe_steps(steps: Iterable[_NormStep]) -> List[_NormStep]:
    seen: set[tuple[str, str]] = set()
    result: List[_NormStep] = []
    for a in steps:
        key = (_norm(a.domain).lower(), _norm(a.what).lower())
        if not a.what or key in seen:
            continue
        seen.add(key)
        result.append(a)
    return result


def _get_top_patterns(patterns: List[_PatternLike]) -> List[_PatternLike]:
    """Порядок задаёт pattern_ranker (клинический приоритет), не пересортировываем."""
    return list(patterns)


def _risk_level(r: Any) -> str:
    return str(getattr(r, "level", "low") or "low").lower()


def _risk_domain(r: Any) -> str:
    return _norm(getattr(r, "domain", "") or "")


def _get_top_risk(risks: List[Any]) -> Any | None:
    if not risks:
        return None
    return sorted(
        risks,
        key=lambda r: (RISK_LEVEL_SCORE.get(_risk_level(r), 0), float(getattr(r, "score", 0) or 0)),
        reverse=True,
    )[0]


def _final_priority_from_score(score: int) -> str:
    for threshold, label in FINAL_PRIORITY_BANDS:
        if score >= threshold:
            return label
    return "low"


def _action_matches_pattern(action: _NormStep, pattern: _PatternLike) -> bool:
    allowed_domains = PATTERN_DOMAIN_MAP.get(pattern.code, [])
    domain = _norm(action.domain)
    if domain in allowed_domains:
        return True

    low_what = _norm(action.what).lower()
    low_pattern = _norm(pattern.label).lower()

    if pattern.category == "hematology" and any(k in low_what for k in ["ферритин", "желез", "оак", "трансферрин"]):
        return True
    if pattern.category == "lipid" and any(k in low_what for k in ["липид", "apob", "липопротеин", "липидограм"]):
        return True
    if pattern.category == "glucose" and any(k in low_what for k in ["глюкоз", "homa", "инсулин", "hba1c"]):
        return True
    if pattern.category == "vitamin" and any(k in low_what for k in ["витамин d", "25(oh)", "кальциферол"]):
        return True
    if pattern.category in ("urinary", "urine") and any(k in low_what for k in ["оам", "моч", "уролог"]):
        return True

    if low_pattern and low_pattern in low_what:
        return True

    return False


def prioritize_actions(
    patterns: List[_PatternLike],
    next_steps: List[Any],
    risks: List[Any] | None = None,
    patient_age: Optional[int] = None,
) -> List[PrioritizedAction]:
    """
    Сортировка и скоринг действий по связи с P1/P2, доменом риска и возрасту.
    """
    risks = risks or []
    normalized = [_normalize_step(s) for s in next_steps if _normalize_step(s).what]
    normalized = _dedupe_steps(normalized)
    sorted_patterns = _get_top_patterns(list(patterns))
    top_risk = _get_top_risk(list(risks))

    results: List[PrioritizedAction] = []

    for action in normalized:
        if not action.patient_visible and not action.physician_visible:
            continue

        score = BASE_PRIORITY_SCORE.get(action.priority, 10)
        linked_patterns: List[str] = []

        for idx, pattern in enumerate(sorted_patterns[:4]):
            if not _action_matches_pattern(action, pattern):
                continue

            linked_patterns.append(pattern.code)

            if pattern.level == "P1":
                if idx == 0:
                    score += 18
                elif idx == 1:
                    score += 12
                else:
                    score += 8
            else:
                score += 4

            if pattern.confidence >= 0.9:
                score += 3
            elif pattern.confidence >= 0.75:
                score += 1

        if top_risk:
            score += RISK_LEVEL_SCORE.get(_risk_level(top_risk), 0)

            low_domain = _norm(action.domain).lower()
            low_risk_domain = _risk_domain(top_risk).lower()

            if "cardio" in low_risk_domain or "metabolic" in low_risk_domain:
                if any(k in low_domain for k in ["липид", "эндокрин", "углевод"]):
                    score += 5
            if "hemat" in low_risk_domain:
                if any(k in low_domain for k in ["гемат", "желез", "оак"]):
                    score += 5
            if "urinary" in low_risk_domain:
                if any(k in low_domain for k in ["моч", "почки", "уролог"]):
                    score += 5

        if patient_age is not None and patient_age < 18:
            low_what = _norm(action.what).lower()
            if any(k in low_what for k in ["ферритин", "желез", "оак", "глюкоз", "витамин d"]):
                score += 4

        final_priority = _final_priority_from_score(score)

        results.append(
            PrioritizedAction(
                domain=action.domain,
                what=action.what,
                why=action.why,
                base_priority=action.priority,
                final_priority=final_priority,
                score=score,
                linked_patterns=linked_patterns,
            )
        )

    results.sort(
        key=lambda x: (
            {"urgent": 0, "high": 1, "medium": 2, "low": 3}.get(x.final_priority, 9),
            -x.score,
            x.what.lower(),
        )
    )

    return results


def prioritized_actions_to_strings(actions: List[PrioritizedAction], limit: int = 8) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for action in actions[: max(limit * 2, 8)]:
        text = _norm(action.what)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def prioritized_actions_to_table_rows(actions: List[PrioritizedAction]) -> List[list[str]]:
    return [
        [
            a.domain,
            a.what,
            a.why,
            a.base_priority,
            a.final_priority,
            str(a.score),
        ]
        for a in actions
    ]


def prioritize_actions_from_patterns(
    ranked: List[_PatternLike],
    patient_meta: dict[str, Any],
) -> List[str]:
    """Короткие рекомендации по кодам паттернов (добавляются как отдельные шаги до скоринга)."""
    _ = patient_meta
    actions: List[str] = []
    codes = {p.code for p in ranked}
    if "iron_deficiency_pattern" in codes:
        actions.append(
            "Оценка железа: ферритин, ОАК в динамике, при необходимости насыщение трансферрина"
        )
    if "atherogenic_dyslipidemia" in codes:
        actions.append("Обсуждение липидного профиля с врачом; при необходимости повтор липидограммы, ApoB / липопротеин(a)")
    if "vitamin_d_insufficiency" in codes:
        actions.append("Контроль витамина D и целевых уровней — по назначению врача и референсу лаборатории")
    return actions
