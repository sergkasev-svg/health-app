"""Общие утилиты для JSON-пакетов clinical scenario v2 (female / fatigue / GI).

Подписи анализов по кодам; формат приложения к ответу и structured payload для API."""

from __future__ import annotations

from typing import Any

# Объединённый справочник кодов из female_health / fatigue_scenarios_v2 / gi_scenarios_v2.
LAB_CODE_TO_RU: dict[str, str] = {
    # female / общие
    "cbc": "общий анализ крови (ОАК)",
    "ferritin": "ферритин",
    "vitamin_b6_optional": "витамин B6 (по показаниям)",
    "magnesium_optional": "магний (по показаниям)",
    "vitamin_d": "витамин D",
    "tsh": "ТТГ (щитовидная железа)",
    "ft4_if_needed": "свободный T4 (по показаниям)",
    "female_sex_hormones_by_cycle_day": "половые гормоны с привязкой к дню цикла (по назначению врача)",
    "ferritin_optional": "ферритин (по показаниям)",
    "vitamin_d_optional": "витамин D (по показаниям)",
    "sex_hormones_if_indicated": "анализы половых гормонов (по показаниям)",
    "glucose_fasting": "глюкоза натощак",
    "insulin_fasting": "инсулин натощак",
    "homa_ir_if_possible": "оценка инсулинорезистентности (HOMA-IR, если доступно)",
    "b12_optional": "витамин B12 (по показаниям)",
    "b12": "витамин B12",
    "vitamin_b12": "витамин B12",
    "cbc_optional": "ОАК (по показаниям)",
    "tsh_optional": "ТТГ (по показаниям)",
    "basic_biochemistry_if_persistent": "базовая биохимия крови (при стойких симптомах)",
    "cbc_if_heavy_bleeding": "ОАК (при обильном кровотечении)",
    "ferritin_if_heavy_bleeding": "ферритин (при обильном кровотечении)",
    "gynecology_followup": "очный приём гинеколога (по ситуации)",
    "glucose_fasting_optional": "глюкоза натощак (по показаниям)",
    "insulin_optional": "инсулин (по показаниям)",
    # fatigue
    "cbc_if_persistent": "ОАК (при стойких симптомах)",
    "ferritin_if_persistent": "ферритин (при стойких симптомах)",
    "tsh_if_persistent": "ТТГ (при стойких симптомах)",
    "crp_optional": "С-реактивный белок (по показаниям)",
    "basic_biochemistry_optional": "базовая биохимия крови (по показаниям)",
    "repeat_cbc_if_needed": "повторный ОАК (по показаниям)",
    "none_first_without_context": "без анализов на первом шаге без контекста",
    "basic_biochemistry": "базовая биохимия крови",
    # gi
    "gi_workup_if_persistent": "обследование ЖКТ (при стойких симптомах)",
    "alt_if_recurrent": "АЛТ (при повторяющихся эпизодах)",
    "ast_if_recurrent": "АСТ (при повторяющихся эпизодах)",
    "bilirubin_if_recurrent": "билирубин (при повторяющихся эпизодах)",
    "ggt_if_recurrent": "ГГТ (при повторяющихся эпизодах)",
    "amylase_if_recurrent": "амилаза (при повторяющихся эпизодах)",
    "lipase_if_recurrent": "липаза (при повторяющихся эпизодах)",
    "none_initial_if_mild": "без анализов при лёгком течении",
    "cbc_if_severe": "ОАК (при тяжёлом течении)",
    "crp_if_fever": "СРБ (при лихорадке)",
    "alt": "АЛТ",
    "ast": "АСТ",
    "bilirubin_total": "билирубин общий",
    "ggt": "ГГТ",
    "alp_optional": "щелочная фосфатаза (по показаниям)",
    "amylase_optional": "амилаза (по показаниям)",
    "lipase_optional": "липаза (по показаниям)",
    "electrolytes_optional": "электролиты (по показаниям)",
    "cbc_if_fatigue": "ОАК (при усталости)",
    "ferritin_if_fatigue": "ферритин (при усталости)",
    "vitamin_d_if_fatigue": "витамин D (при усталости)",
    "b12_if_fatigue": "витамин B12 (при усталости)",
}


def lab_codes_to_ru_labels(codes: list[Any]) -> list[str]:
    """Человекочитаемые подписи для кодов анализов из JSON."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in codes or []:
        code = str(raw or "").strip().lower()
        if not code:
            continue
        label = LAB_CODE_TO_RU.get(code)
        if not label:
            base = code.replace("_optional", "").replace("_if_needed", "").replace("_if_indicated", "")
            base = base.replace("_if_possible", "").replace("_if_heavy_bleeding", "").replace("_if_persistent", "")
            base = base.replace("_if_recurrent", "").replace("_if_fatigue", "").replace("_if_fever", "")
            base = base.replace("_if_severe", "").replace("_if_mild", "")
            label = base.replace("_", " ").strip() or code
            if code.endswith("_optional") or "_if_" in code:
                label = f"{label} (по показаниям)"
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


def format_appendix_from_scenario_row(
    fh: dict[str, Any] | None,
    *,
    max_questions: int = 3,
    max_labs: int = 5,
    max_flags: int = 3,
) -> str:
    """Блок для чата: уточнения, анализы, красные флаги, CTA."""
    if not fh:
        return ""
    parts: list[str] = []
    qs = [str(x).strip() for x in (fh.get("followup_questions") or []) if str(x).strip()][:max_questions]
    if qs:
        parts.append("Что уточнить дальше:\n" + "\n".join(f"— {q}" for q in qs))
    codes = fh.get("labs_priority")
    if isinstance(codes, list) and codes:
        labs = lab_codes_to_ru_labels([str(x) for x in codes])[:max_labs]
    else:
        labs = lab_codes_to_ru_labels(list(fh.get("suggested_labs") or []))[:max_labs]
    if labs:
        parts.append("Имеет смысл обсудить с врачом анализы (по ситуации):\n" + "\n".join(f"— {x}" for x in labs))
    flags = [str(x).strip() for x in (fh.get("red_flags") or []) if str(x).strip()][:max_flags]
    if flags:
        parts.append("Срочно очно / скорая, если:\n" + "\n".join(f"— {x}" for x in flags))
    cta = str(fh.get("next_step_cta") or fh.get("cta_next_step") or "").strip()
    if cta:
        parts.append(f"Дальше: {cta}")
    if not parts:
        return ""
    return "\n\n" + "\n\n".join(parts)


def build_structured_v2_payload(
    fh: dict[str, Any],
    *,
    bundle_version: str,
    bundle_locale: Any,
    bundle_category: Any,
    data_source: str,
) -> dict[str, Any]:
    """Единый объект для structured.*_scenario в API."""
    codes = list(fh.get("suggested_labs") or [])
    pri = fh.get("labs_priority")
    pri_list = list(pri) if isinstance(pri, list) else []
    cta = fh.get("next_step_cta") or fh.get("cta_next_step")
    priority_val = fh.get("priority_score")
    if priority_val is None:
        priority_val = fh.get("priority")
    return {
        "scenario_id": fh.get("scenario_id"),
        "pattern_id": fh.get("pattern_id"),
        "priority_score": priority_val,
        "priority": fh.get("priority"),
        "risk_level": fh.get("risk_level"),
        "routing": fh.get("routing"),
        "requires_cycle_context": fh.get("requires_cycle_context"),
        "requires_context_flags": fh.get("requires_context_flags"),
        "paywall_candidate": fh.get("paywall_candidate"),
        "confidence_rules": fh.get("confidence_rules"),
        "bundle_version": bundle_version,
        "bundle_locale": bundle_locale,
        "bundle_category": bundle_category,
        "data_source": data_source,
        "dominant_drivers": fh.get("dominant_drivers"),
        "followup_questions": fh.get("followup_questions"),
        "suggested_labs_codes": codes,
        "suggested_labs_labels": lab_codes_to_ru_labels(codes),
        "labs_priority_codes": pri_list,
        "labs_priority_labels": lab_codes_to_ru_labels(pri_list),
        "red_flags": fh.get("red_flags"),
        "patient_safe_summary": fh.get("patient_safe_summary"),
        "doctor_safe_summary": fh.get("doctor_safe_summary"),
        "next_step_cta": cta,
        "cta_next_step": cta,
    }