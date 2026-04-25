from __future__ import annotations

from typing import Any

DISCLAIMER_TEXT = "Информация носит справочный характер и не заменяет очный осмотр врача."


def _uniq(items: list[str], limit: int = 8) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        v = str(raw or "").strip()
        if not v:
            continue
        key = v.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
        if len(out) >= limit:
            break
    return out


def _hypothesis_rows(top_hypotheses: list[Any], fallback_message: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in top_hypotheses or []:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("label") or "").strip()
            if not name:
                continue
            why = str(item.get("explanation") or "").strip()
            rows.append(
                {
                    "name": name,
                    "likelihood": str(item.get("likelihood") or "possible").strip() or "possible",
                    "why_it_fits": [why] if why else [],
                }
            )
        elif isinstance(item, str) and item.strip():
            rows.append({"name": item.strip(), "likelihood": "possible", "why_it_fits": []})
    if not rows:
        rows = [{"name": fallback_message, "likelihood": "possible", "why_it_fits": []}]
    return rows[:3]


def render_safe_summary_bundle(
    *,
    user_message: str,
    top_hypotheses: list[Any] | None = None,
    structured_payload: dict[str, Any] | None = None,
    guidance_context: dict[str, Any] | None = None,
    triage_data: dict[str, Any] | None = None,
    followup_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(structured_payload or {})
    ctx = dict(guidance_context or {})
    safe = dict(ctx.get("safe_summary") or {})
    triage = dict(triage_data or {})
    fstate = dict(followup_state or {})

    fallback_hyp = "Требуется очная верификация причины по клиническим данным."
    hypothesis_rows = _hypothesis_rows(list(top_hypotheses or []), fallback_hyp)
    hypotheses = [str(h.get("name") or "").strip() for h in hypothesis_rows if str(h.get("name") or "").strip()]

    treatment_plan = payload.get("treatment_plan") if isinstance(payload.get("treatment_plan"), dict) else {}
    what_to_do = _uniq(
        list(treatment_plan.get("what_to_do") or [])
        + list(payload.get("care_plan_today") or [])
        + list(safe.get("first_line") or []),
        6,
    )
    what_not_to_do = _uniq(list(treatment_plan.get("what_not_to_do") or []), 5)
    medications_safe = _uniq(list(treatment_plan.get("medications_safe_general") or []), 6)
    medications_doctor_only = _uniq(list(treatment_plan.get("medications_doctor_only") or []), 6)
    nutrition = _uniq(list(treatment_plan.get("nutrition") or []) + list(payload.get("nutrition_advice") or []) + list(safe.get("nutrition") or []), 6)
    activity = _uniq(list(treatment_plan.get("activity") or []) + list(payload.get("activity_advice") or []) + list(safe.get("activity") or []), 6)

    checks = _uniq(
        list(payload.get("recommended_labs") or [])
        + list(payload.get("exam_recommendations") or [])
        + list(safe.get("tests") or []),
        8,
    )
    urgent_points = _uniq(
        list(payload.get("when_urgent") or [])
        + list(safe.get("red_flags") or [])
        + ([str(triage.get("reason") or "").strip()] if str(triage.get("reason") or "").strip() else []),
        6,
    )
    if not urgent_points:
        urgent_points = ["При ухудшении состояния или появлении красных флагов обратитесь за очной неотложной помощью."]

    answered_slots = list((fstate.get("answered_slots") or {}).keys())
    summary_lines: list[str] = []
    summary_lines.append("Гипотезы:")
    summary_lines.extend([f"- {x}" for x in hypotheses[:3]])
    summary_lines.append("Что проверить:")
    summary_lines.extend([f"- {x}" for x in (checks[:4] or ["Очный осмотр и базовые анализы по назначению врача."])])
    summary_lines.append("Что делать:")
    summary_lines.extend([f"- {x}" for x in (what_to_do[:4] or ["Щадящий режим, контроль симптомов и динамики."])])
    summary_lines.append("Чего не делать:")
    summary_lines.extend([f"- {x}" for x in (what_not_to_do[:3] or ["Не откладывать очный осмотр при ухудшении."])])
    summary_lines.append("Медикаментозно (безопасно общие подходы):")
    summary_lines.extend([f"- {x}" for x in (medications_safe[:3] or ["Применять препараты только по инструкции и с учетом противопоказаний."])])
    summary_lines.append("Немедикаментозно, питание и активность:")
    combined_lifestyle = _uniq((nutrition[:3] + activity[:3]), 6)
    summary_lines.extend([f"- {x}" for x in (combined_lifestyle or ["Сон, питьевой режим, умеренная нагрузка по самочувствию."])])
    summary_lines.append("Когда срочно к врачу:")
    summary_lines.extend([f"- {x}" for x in urgent_points[:4]])
    summary_lines.append(DISCLAIMER_TEXT)

    patient_response = "\n".join(summary_lines).strip()
    patient_summary = (
        "Собран безопасный клинический итог: гипотезы, проверки, план действий и признаки срочности."
    )

    safe_summary_renderer = {
        "enabled": True,
        "source": "confidence_gate",
        "answered_slots": answered_slots,
        "hypotheses": hypotheses[:3],
        "what_to_check": checks,
        "what_to_do": what_to_do,
        "what_not_to_do": what_not_to_do,
        "medications_safe_general": medications_safe,
        "medications_doctor_only": medications_doctor_only,
        "nutrition": nutrition,
        "activity": activity,
        "when_urgent": urgent_points,
    }

    return {
        "patient_facing_response": patient_response,
        "patient_summary": patient_summary,
        "top_hypotheses": hypothesis_rows,
        "recommended_labs": checks,
        "care_plan_today": what_to_do,
        "when_urgent": urgent_points,
        "treatment_plan": {
            "what_to_do": what_to_do,
            "what_not_to_do": what_not_to_do,
            "medications_safe_general": medications_safe,
            "medications_doctor_only": medications_doctor_only,
            "nutrition": nutrition,
            "activity": activity,
        },
        "safe_summary_renderer": safe_summary_renderer,
    }

