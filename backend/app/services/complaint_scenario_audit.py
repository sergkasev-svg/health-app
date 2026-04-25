from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from app.services.complaint_reference import get_prioritized_complaints
from app.services.consultation_orchestrator import ConsultationOrchestratorAdapter


_UTC = timezone.utc
_DEFAULT_ARTIFACTS_DIR = Path("./quality_artifacts")
_STATE_FILE = _DEFAULT_ARTIFACTS_DIR / "complaint_scenario_audit_state.json"


@dataclass
class ScenarioAuditCase:
    case_id: str
    complaint_id: str
    source: str
    user_text: str
    complaint_name: str
    category: str
    red_flags: list[str]
    must_ask: list[str]
    key_symptoms: list[str]
    urgency_level: str


@dataclass
class ScenarioAuditEvaluation:
    case_id: str
    complaint_id: str
    source: str
    user_text: str
    complaint_name: str
    category: str
    final_score_100: float
    component_scores: dict[str, float]
    problem_tags: list[str]
    fix_suggestions: list[str]
    branch: str
    matched: bool
    patient_response: str
    followup_questions: list[str]
    care_level: str


@dataclass
class ScenarioAuditResult:
    summary: dict[str, Any]
    score_distribution: dict[str, Any]
    top_problems: list[dict[str, Any]]
    low_score_cases: list[dict[str, Any]]
    reminder: dict[str, Any]


def _safe_lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _norm_text(value: str) -> str:
    text = str(value or "").lower().replace("ё", "е")
    text = re.sub(r"[^\w\sа-яa-z0-9]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _contains_any(text: str, markers: list[str]) -> bool:
    if not text:
        return False
    return any(m in text for m in markers)


def _is_high_risk_case(case: ScenarioAuditCase) -> bool:
    urgency = _safe_lower(case.urgency_level)
    if urgency in {"urgent", "emergency", "red"}:
        return True
    text = _norm_text(case.user_text)
    critical_markers = (
        "боль в груди",
        "одыш",
        "обмор",
        "кровь в рвоте",
        "черный стул",
        "чёрный стул",
        "не могу говорить",
        "перекос лица",
        "сильная слабость",
        "судорог",
    )
    if any(
        k in text
        for k in critical_markers
    ):
        return True
    # Avoid over-marking high-risk based on broad scenario red_flag lists.
    return False


def _extract_keywords(case: ScenarioAuditCase, limit: int = 10) -> list[str]:
    parts = [
        case.complaint_name,
        " ".join(case.key_symptoms or []),
        " ".join(case.red_flags or []),
    ]
    tokens = _norm_text(" ".join(parts)).split()
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if len(token) < 4:
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= max(1, int(limit)):
            break
    return out


def _expected_branches(case: ScenarioAuditCase) -> set[str]:
    text = _norm_text(f"{case.category} {case.complaint_name} {case.user_text}")
    expected: set[str] = set()
    has_infectious_context = any(k in text for k in ("температур", "39", "38", "лихорад", "каш", "горл", "сопл", "насморк", "озноб"))
    if any(
        k in text
        for k in (
            "после еды",
            "еда",
            "пищ",
            "тошнота после",
            "рвота после",
            "диарея после",
            "после творога",
            "после сыра",
            "после вина",
            "творог",
            "сыр",
            "молок",
        )
    ):
        expected.add("food")
    if any(k in text for k in ("груд", "давлен", "сердц", "пульс", "кардио")):
        expected.add("cardio")
    if any(k in text for k in ("живот", "диаре", "понос", "рвот", "изжог", "жкт", "гастро")):
        expected.add("gastro")
    if any(k in text for k in ("каш", "горл", "насморк", "орви", "дых", "resp")):
        expected.add("respiratory")
    neuro_specific = any(
        k in text
        for k in (
            "онем",
            "слабост в руке",
            "слабост в ноге",
            "перекос лица",
            "не могу говорить",
            "нарушение речи",
            "внезапная",
            "судорог",
            "невро",
            "neuro",
        )
    )
    has_headache_word = "голов" in text
    if neuro_specific or (has_headache_word and not has_infectious_context):
        expected.add("neuro")
    if any(k in text for k in ("моч", "цистит", "поясниц", "urinary", "дизур")):
        expected.add("urinary")
    if any(k in text for k in ("сып", "зуд", "аллерг", "крапив", "кожа")):
        expected.add("allergy_skin")
    if any(k in text for k in ("месяч", "беремен", "гинек", "влагалищ", "women")):
        expected.add("women_health")
    if any(k in text for k in ("ребен", "ребён", "педиатр", "дет")):
        expected.add("pediatric")
    if any(k in text for k in ("ухо", "пазух", "миндалин", "лор", "ent")):
        expected.add("ent")
    if any(k in text for k in ("зуб", "десн", "рот", "oral")):
        expected.add("oral_cavity")
    if any(k in text for k in ("колен", "голеностоп", "сустав", "травм", "ортоп")):
        expected.add("orthopedics")
    if any(k in text for k in ("слабость", "устал", "дефицит", "анем")):
        expected.add("fatigue_deficiency")
    if not expected:
        expected.add("general")
    return expected


def _is_branch_match(expected: str, branch: str, doctor_primary_scenario_id: str) -> bool:
    expected = _safe_lower(expected)
    branch_l = _safe_lower(branch)
    scenario_id = _safe_lower(doctor_primary_scenario_id)
    if expected in {"", "general"}:
        return True
    if expected == "food":
        return ("food" in branch_l) or ("food" in scenario_id) or ("postmeal" in scenario_id)
    if expected in {"cardio", "gastro", "respiratory", "neuro", "urinary", "allergy_skin", "women_health", "pediatric", "ent"}:
        return expected in scenario_id or expected in branch_l
    if expected == "oral_cavity":
        return ("oral" in scenario_id) or ("oral" in branch_l) or ("tooth" in scenario_id)
    if expected == "orthopedics":
        return ("orthoped" in scenario_id) or ("orthoped" in branch_l) or any(
            x in scenario_id for x in ("knee", "ankle", "back", "shoulder")
        )
    if expected == "fatigue_deficiency":
        return ("fatigue" in scenario_id) or ("deficiency" in scenario_id)
    return expected in scenario_id or expected in branch_l


def _is_any_branch_match(expected_candidates: set[str], branch: str, doctor_primary_scenario_id: str) -> bool:
    for expected in expected_candidates:
        if _is_branch_match(expected, branch, doctor_primary_scenario_id):
            return True
    return False


def _score_response(case: ScenarioAuditCase, payload: dict[str, Any], *, strict_mode: bool = False) -> ScenarioAuditEvaluation:
    patient_response = str(payload.get("patient_response") or "").strip()
    followup_questions = [str(x).strip() for x in (payload.get("followup_questions") or []) if str(x).strip()]
    care_level = str(payload.get("care_level") or "").strip()
    branch = str(payload.get("branch") or "").strip()
    matched = bool(payload.get("matched"))
    doctor_payload = payload.get("doctor_payload") if isinstance(payload.get("doctor_payload"), dict) else {}
    doctor_primary = str(doctor_payload.get("primary_scenario_id") or "").strip()

    low = _norm_text(patient_response)
    explanation_markers = [
        "вероят",
        "скорее",
        "похоже",
        "может быть",
        "главная зона внимания",
        "ветке",
    ]
    action_markers = [
        "что делать",
        "делать сейчас",
        "пейте",
        "наблюда",
        "отдых",
        "избег",
        "обратитесь",
    ]
    urgency_markers = [
        "срочно",
        "неотлож",
        "103",
        "скорая",
        "вызовите",
        "опасн",
        "urgent",
        "когда лучше не тянуть",
        "когда срочно",
        "обморок",
        "боль в груди",
        "одышка",
    ]

    component_scores: dict[str, float] = {
        "response_presence_and_clarity": 0.0,
        "clinical_explanation": 0.0,
        "actionable_next_steps": 0.0,
        "urgency_and_safety": 0.0,
        "followup_quality": 0.0,
    }
    problem_tags: list[str] = []

    if len(patient_response) >= 70:
        component_scores["response_presence_and_clarity"] = 20.0
    elif len(patient_response) >= 35:
        component_scores["response_presence_and_clarity"] = 10.0
        problem_tags.append("short_response")
    else:
        problem_tags.append("empty_or_too_short_response")

    if _contains_any(low, explanation_markers):
        component_scores["clinical_explanation"] = 20.0
    else:
        problem_tags.append("missing_probable_explanation")

    if _contains_any(low, action_markers):
        component_scores["actionable_next_steps"] = 20.0
    else:
        problem_tags.append("missing_action_plan")

    is_high_risk = _is_high_risk_case(case)
    has_urgency = _contains_any(low, urgency_markers)
    if is_high_risk:
        if has_urgency:
            component_scores["urgency_and_safety"] = 20.0
        else:
            problem_tags.append("missing_urgency_guidance_high_risk")
    else:
        # For low-risk complaints we still prefer a safe "when to seek urgent help" line.
        component_scores["urgency_and_safety"] = 12.0 if has_urgency else 18.0
        if not has_urgency:
            problem_tags.append("limited_safety_net_guidance")

    if followup_questions:
        component_scores["followup_quality"] = 20.0
    elif "?" in patient_response and len(patient_response) >= 30:
        component_scores["followup_quality"] = 12.0
        problem_tags.append("followup_question_not_structured")
    elif case.must_ask:
        problem_tags.append("missing_followup_question")

    keywords = _extract_keywords(case)
    keyword_hits = sum(1 for k in keywords if k in low)
    if keywords and keyword_hits <= 0:
        problem_tags.append("low_keyword_alignment")
    elif keywords and keyword_hits == 1:
        problem_tags.append("partial_keyword_alignment")

    strict_penalty = 0.0
    if strict_mode:
        expected = _expected_branches(case)
        if not matched:
            strict_penalty += 8.0
            problem_tags.append("strict_unmatched_case")

        branch_match = _is_any_branch_match(expected, branch, doctor_primary)
        if not branch_match:
            strict_penalty += 15.0
            problem_tags.append("strict_domain_route_mismatch")

        keyword_ratio = (keyword_hits / max(1, len(keywords))) if keywords else 1.0
        if keyword_ratio < 0.2:
            strict_penalty += 8.0
            problem_tags.append("strict_low_keyword_alignment")

        if "пока данных недостаточно" in low and len(followup_questions) <= 1 and len(patient_response) < 350:
            strict_penalty += 6.0
            problem_tags.append("strict_over_generic_response")

        if care_level == "self_care_or_clarify" and _is_high_risk_case(case):
            strict_penalty += 6.0
            problem_tags.append("strict_undertriage_risk")

    if strict_penalty > 0:
        component_scores["strict_penalty"] = -round(strict_penalty, 1)

    fixes = _fix_suggestions(problem_tags)
    final_score = max(0.0, min(100.0, round(float(sum(component_scores.values())), 1)))
    return ScenarioAuditEvaluation(
        case_id=case.case_id,
        complaint_id=case.complaint_id,
        source=case.source,
        user_text=case.user_text,
        complaint_name=case.complaint_name,
        category=case.category,
        final_score_100=final_score,
        component_scores=component_scores,
        problem_tags=problem_tags,
        fix_suggestions=fixes,
        branch=branch,
        matched=matched,
        patient_response=patient_response,
        followup_questions=followup_questions,
        care_level=care_level,
    )


def _fix_suggestions(tags: list[str]) -> list[str]:
    mapping = {
        "empty_or_too_short_response": "Добавить обязательный минимальный шаблон ответа: вероятная причина + что делать сейчас + когда срочно.",
        "short_response": "Поднять минимальную длину patient-safe блока и не завершать ответ до выдачи плана действий.",
        "missing_probable_explanation": "Всегда включать 1-2 вероятные причины в первых строках ответа.",
        "missing_action_plan": "Добавить фиксированный блок 'Что делать сейчас' минимум из 2 практических шагов.",
        "missing_urgency_guidance_high_risk": "Для кейсов с red flags принудительно добавлять четкие триггеры срочного обращения.",
        "limited_safety_net_guidance": "Добавить одну safety-net строку даже в неострых сценариях.",
        "missing_followup_question": "Включить правило: минимум 1 релевантный follow-up вопрос при наличии must_ask.",
        "followup_question_not_structured": "Пробрасывать followup_questions как явный список, не только в свободном тексте.",
        "low_keyword_alignment": "Усилить lexical alignment: повторять ключевые слова жалобы в итоговом ответе.",
        "partial_keyword_alignment": "Добавить 1-2 ключевых симптома пользователя в формулировку объяснения.",
        "strict_unmatched_case": "Проверить маршрутизацию: кейс не считается matched, нужен fallback с полной клинической структурой.",
        "strict_domain_route_mismatch": "Согласовать route и сценарий с доменом жалобы (cardio/gastro/neuro и т.д.).",
        "strict_low_keyword_alignment": "В строгом режиме добавлять не меньше 2 ключевых маркеров из жалобы в итоговый ответ.",
        "strict_over_generic_response": "Избегать шаблона 'данных недостаточно' без доменного объяснения и короткого плана.",
        "strict_undertriage_risk": "Усилить правило care_level: high-risk кейсы не должны оставаться в self_care_or_clarify.",
    }
    out: list[str] = []
    for tag in tags:
        msg = mapping.get(tag)
        if msg and msg not in out:
            out.append(msg)
    return out


def _build_cases(target_count: int = 300, max_rows: int = 1000) -> list[ScenarioAuditCase]:
    rows = get_prioritized_complaints(limit=max_rows)
    cases: list[ScenarioAuditCase] = []
    serial = 1

    for row in rows:
        complaint_id = str(row.get("id") or f"complaint_{serial}")
        complaint = str(row.get("complaint") or row.get("name") or "").strip()
        if not complaint:
            continue

        must_ask = [str(x).strip() for x in (row.get("anamnesis_questions") or []) if str(x).strip()]
        red_flags = [str(x).strip() for x in (row.get("red_flags") or []) if str(x).strip()]
        key_symptoms = [str(x).strip() for x in (row.get("symptoms") or row.get("key_symptoms") or []) if str(x).strip()]
        category = str(row.get("category") or "").strip()
        urgency_level = str(row.get("urgency_level") or "").strip()
        source = str(row.get("source") or "complaint_reference").strip()

        def add_case(user_text: str, source_tag: str) -> None:
            nonlocal serial
            cases.append(
                ScenarioAuditCase(
                    case_id=f"scn_{serial:04d}",
                    complaint_id=complaint_id,
                    source=source_tag,
                    user_text=user_text.strip(),
                    complaint_name=complaint,
                    category=category,
                    red_flags=red_flags,
                    must_ask=must_ask,
                    key_symptoms=key_symptoms,
                    urgency_level=urgency_level,
                )
            )
            serial += 1

        add_case(complaint, "complaint_name")
        if len(cases) >= target_count:
            break

        for phr in (row.get("common_user_phrasings") or [])[:4]:
            phr_text = str(phr).strip()
            if not phr_text:
                continue
            # Avoid noisy single-token artifacts from weak phrase extraction.
            if len(phr_text) < 8:
                continue
            if len(phr_text.split()) < 2:
                continue
            add_case(phr_text, "common_user_phrasing")
            if len(cases) >= target_count:
                break
        if len(cases) >= target_count:
            break

    return cases[:target_count]


def _aggregate_distribution(scores: list[float]) -> dict[str, Any]:
    if not scores:
        return {"p50": 0.0, "p75": 0.0, "p90": 0.0, "min": 0.0, "max": 0.0}

    sorted_scores = sorted(scores)

    def pct(q: float) -> float:
        if not sorted_scores:
            return 0.0
        idx = int(round((len(sorted_scores) - 1) * q))
        idx = max(0, min(idx, len(sorted_scores) - 1))
        return float(sorted_scores[idx])

    return {
        "p50": round(pct(0.50), 1),
        "p75": round(pct(0.75), 1),
        "p90": round(pct(0.90), 1),
        "min": round(float(sorted_scores[0]), 1),
        "max": round(float(sorted_scores[-1]), 1),
    }


def _problem_table(evals: list[ScenarioAuditEvaluation], limit: int = 12) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for ev in evals:
        for tag in ev.problem_tags:
            counts[tag] = counts.get(tag, 0) + 1
    rows = [{"problem": k, "count": v} for k, v in counts.items()]
    rows.sort(key=lambda x: int(x["count"]), reverse=True)
    return rows[: max(1, int(limit))]


def _low_score_cases(evals: list[ScenarioAuditEvaluation], limit: int = 40) -> list[dict[str, Any]]:
    rows = sorted(evals, key=lambda x: x.final_score_100)
    out: list[dict[str, Any]] = []
    for ev in rows[: max(1, int(limit))]:
        out.append(
            {
                "case_id": ev.case_id,
                "complaint_id": ev.complaint_id,
                "complaint_name": ev.complaint_name,
                "category": ev.category,
                "score_100": ev.final_score_100,
                "problem_tags": ev.problem_tags,
                "fix_suggestions": ev.fix_suggestions[:3],
                "branch": ev.branch,
                "matched": ev.matched,
                "care_level": ev.care_level,
                "user_text": ev.user_text,
                "patient_response": ev.patient_response,
                "followup_questions": ev.followup_questions,
            }
        )
    return out


def _iso_now() -> str:
    return datetime.now(tz=_UTC).isoformat()


def _check_reminder(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(tz=_UTC)
    state = {}
    if _STATE_FILE.exists():
        try:
            state = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    last_run_raw = str(state.get("last_run_at") or "").strip()
    if not last_run_raw:
        return {"due": True, "last_run_at": "", "next_reminder_at": ""}
    try:
        last_run = datetime.fromisoformat(last_run_raw)
    except Exception:
        return {"due": True, "last_run_at": "", "next_reminder_at": ""}
    next_reminder = last_run + timedelta(days=3)
    return {
        "due": now >= next_reminder,
        "last_run_at": last_run.isoformat(),
        "next_reminder_at": next_reminder.isoformat(),
    }


def _write_state(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(tz=_UTC)
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_run_at": now.isoformat(),
        "next_reminder_at": (now + timedelta(days=3)).isoformat(),
    }
    _STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def run_complaint_scenario_audit(
    *,
    target_count: int = 300,
    low_score_threshold: float = 70.0,
    strict_mode: bool = False,
) -> ScenarioAuditResult:
    cases = _build_cases(target_count=max(300, int(target_count or 300)))
    adapter = ConsultationOrchestratorAdapter()

    evaluations: list[ScenarioAuditEvaluation] = []
    for case in cases:
        payload = adapter.run_consultation(
            user_id=None,
            user_text=case.user_text,
            debug=False,
            extra_context={"chat_history": []},
        )
        evaluations.append(_score_response(case, payload, strict_mode=strict_mode))

    scores = [x.final_score_100 for x in evaluations]
    avg_score = round(float(mean(scores)) if scores else 0.0, 1)
    below_threshold = [x for x in evaluations if x.final_score_100 < float(low_score_threshold)]

    summary = {
        "generated_at": _iso_now(),
        "cases_total": len(evaluations),
        "target_count_requested": int(target_count),
        "strict_mode": bool(strict_mode),
        "average_score_100": avg_score,
        "pass_threshold_100": float(low_score_threshold),
        "passed_count": len(evaluations) - len(below_threshold),
        "failed_count": len(below_threshold),
        "pass_rate": round(((len(evaluations) - len(below_threshold)) / len(evaluations) * 100.0), 1) if evaluations else 0.0,
    }
    reminder_before = _check_reminder()
    reminder_state = _write_state()
    reminder = {
        "before_run": reminder_before,
        "after_run": {
            "due": False,
            "last_run_at": reminder_state.get("last_run_at"),
            "next_reminder_at": reminder_state.get("next_reminder_at"),
        },
    }

    return ScenarioAuditResult(
        summary=summary,
        score_distribution=_aggregate_distribution(scores),
        top_problems=_problem_table(evaluations, limit=12),
        low_score_cases=_low_score_cases(evaluations, limit=40),
        reminder=reminder,
    )


def save_complaint_scenario_audit_report(
    result: ScenarioAuditResult,
    *,
    output_dir: str | Path = _DEFAULT_ARTIFACTS_DIR,
    json_name: str = "complaint_scenario_audit_report.json",
    md_name: str = "complaint_scenario_audit_report.md",
) -> dict[str, Path]:
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    json_path = base / json_name
    md_path = base / md_name

    payload = asdict(result)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append("# Complaint Scenario Audit")
    lines.append("")
    lines.append("## Summary")
    for key, value in result.summary.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Score Distribution")
    for key, value in result.score_distribution.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Top Problems")
    for row in result.top_problems:
        lines.append(f"- {row.get('problem')}: {row.get('count')}")
    lines.append("")
    lines.append("## Low Score Cases (Top 40)")
    for row in result.low_score_cases:
        lines.append(
            f"- [{row.get('score_100')}] {row.get('case_id')} / {row.get('complaint_name')} :: problems={', '.join(row.get('problem_tags') or [])}"
        )
    lines.append("")
    lines.append("## Reminder")
    lines.append(f"- next_reminder_at: {result.reminder.get('after_run', {}).get('next_reminder_at', '')}")
    lines.append("- cadence: every 3 days")
    md_path.write_text("\n".join(lines), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}

