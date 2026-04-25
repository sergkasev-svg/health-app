from __future__ import annotations

from typing import Any


def _bullet(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines if line)


def _extract_titles(cause_ids: list[str], causes_map: dict[str, dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for cause_id in cause_ids:
        cause = causes_map.get(cause_id)
        if not cause:
            continue
        title = str(cause.get("title", cause_id)).strip()
        if title:
            result.append(title)
    return result


def build_urgent_response(
    matched_red_flags: list[str],
    urgent_reason: str | None = None,
) -> dict[str, Any]:
    flags = list(dict.fromkeys(flag for flag in matched_red_flags if flag))

    parts: list[str] = []
    parts.append("Похоже, здесь есть признаки, которые лучше не разбирать как обычную пищевую реакцию.")

    if urgent_reason:
        parts.append(f"Почему нужна срочная оценка:\n{urgent_reason}")
    else:
        parts.append("Почему нужна срочная оценка:\nСимптомы выходят за рамки обычной реакции на еду.")

    if flags:
        parts.append("Что настораживает:\n" + _bullet(flags))

    parts.append(
        "Что делать прямо сейчас:\n"
        + _bullet(
            [
                "не ждать, если состояние ухудшается",
                "не перегружать себя едой",
                "если нет многократной рвоты — пить воду маленькими глотками",
                "обратиться за срочной медицинской помощью",
            ]
        )
    )

    return {
        "mode": "urgent",
        "text": "\n\n".join(parts).strip(),
        "matched_red_flags": flags,
        "urgent_reason": urgent_reason or "",
    }


def build_patient_safe_response(
    *,
    template_name: str,
    templates: dict[str, Any],
    ranked_cause_ids: list[str],
    causes_map: dict[str, dict[str, Any]],
    recommended_tests: list[str] | None = None,
    recurrent: bool = False,
    clarifying_questions: list[str] | None = None,
) -> dict[str, Any]:
    template = templates.get("templates", {}).get(template_name, {})
    if not template:
        template = {}

    cause_titles = _extract_titles(ranked_cause_ids, causes_map)
    most_likely = str(template.get("most_likely", "")).strip()
    alternatives = list(template.get("alternatives", []))
    actions = list(template.get("what_to_do_now", []))
    urgent = list(template.get("urgent_signs", []))
    tests_if_recurrent = list(template.get("tests_if_recurrent", []))

    if recurrent and recommended_tests:
        tests_if_recurrent.extend(recommended_tests)

    parts: list[str] = []

    if most_likely:
        parts.append(f"Что вероятнее всего:\n{most_likely}")

    if cause_titles or alternatives:
        lines: list[str] = []
        for i, title in enumerate(cause_titles[:4], start=1):
            lines.append(f"{i}. {title}")
        for item in alternatives:
            lines.append(f"- {item}")
        parts.append("Какие ещё причины возможны:\n" + "\n".join(lines))

    if actions:
        parts.append("Что делать сейчас:\n" + _bullet(actions))

    if urgent:
        parts.append("Когда лучше не тянуть:\n" + _bullet(urgent))

    if recurrent and tests_if_recurrent:
        deduped = list(dict.fromkeys(tests_if_recurrent))
        parts.append("Если это повторяется:\n" + _bullet(deduped))

    if clarifying_questions:
        parts.append("Чтобы точнее понять ситуацию:\n" + _bullet(clarifying_questions[:3]))

    return {
        "mode": "patient_safe",
        "template": template_name,
        "ranked_cause_ids": ranked_cause_ids,
        "text": "\n\n".join(parts).strip(),
    }


def build_doctor_safe_output(
    *,
    normalized: str,
    zone: str,
    cluster: str,
    trigger_groups: list[str],
    matched_red_flags: list[str],
    cause_scores: dict[str, int],
    ranked_cause_ids: list[str],
    recommended_tests: list[str],
    recurrent: bool,
    evidence_map: dict[str, list[str]] | None = None,
    clarifying_questions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "mode": "doctor_safe",
        "normalized_input": normalized,
        "zone": zone,
        "cluster": cluster,
        "trigger_groups": trigger_groups,
        "matched_red_flags": matched_red_flags,
        "recurrent": recurrent,
        "cause_scores": cause_scores,
        "ranked_causes": ranked_cause_ids,
        "evidence_by_cause": evidence_map or {},
        "recommended_tests_if_recurrent": recommended_tests,
        "clarifying_questions": clarifying_questions or [],
    }

