"""
Clinical routing: (1) маршрут диалога / типов панелей, (2) осевой routing OA physician report.

Правила decision engine:
- document/lab primary выбирается детерминированно (приоритет панелей).
- симптомный маршрут с низкой уверенностью не доминирует над generic_safe.
- red flags → emergency всегда первым.

build_clinical_routing_output — ранжирование осей и user/doctor synthesis для отчёта органических кислот.
Импорт для OA: ``from app.services.clinical_oa_axis_routing import build_clinical_routing_output``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from app.services.clinical_route_conflicts import apply_route_conflicts
from app.services.clinical_routing_models import ClinicalRouteContext, ClinicalRouteDecision
from app.services.document_type_detector import detect_document_type, detect_lab_type, prioritize_lab_types
from app.services.symptom_route_detector import detect_symptom_routes

LAB_TYPE_TO_ROUTE = {
    "organic_acids": "organic_acids_route",
    "cbc": "cbc_route",
    "thyroid": "thyroid_route",
    "lipid": "lipid_route",
    "iron": "iron_route",
    "biochemistry_basic": "biochemistry_basic_route",
    "urine_general": "urine_general_route",
}

# Минимальная уверенность симптом-only ветки, чтобы не подменять generic_safe «шумом».
SYMPTOM_PRIMARY_MIN_CONFIDENCE = 0.55


class ClinicalRoutingEngine:
    def decide(
        self,
        payload: dict[str, Any],
        parsed_documents: list[dict],
        extracted_symptoms: list[str],
        red_flags: list[str],
    ) -> ClinicalRouteDecision:
        user_text = str(payload.get("user_text") or "")
        filename = None
        files = payload.get("uploaded_files") or []
        if files and isinstance(files[0], dict):
            filename = files[0].get("filename") or files[0].get("name")

        combined_text = user_text
        for f in files or []:
            if isinstance(f, dict):
                combined_text += "\n" + str(
                    f.get("extracted_text") or f.get("content") or f.get("text") or f.get("body") or ""
                )

        ctx = ClinicalRouteContext(red_flags=list(red_flags or []))
        debug: dict[str, Any] = {}

        if red_flags:
            return ClinicalRouteDecision(
                primary_route="emergency_route",
                secondary_routes=[],
                blocked_routes=list(LAB_TYPE_TO_ROUTE.values()),
                confidence=1.0,
                reasons=["red_flags: emergency_route override"],
                safety_override=True,
                debug={"context": asdict(ctx), "emergency": True},
            )

        raw_lab_list = detect_lab_type(combined_text, filename)
        lab_list = prioritize_lab_types(raw_lab_list)
        doc_info = detect_document_type(combined_text, filename)
        ctx.detected_lab_types = lab_list
        ctx.detected_document_types = doc_info.get("lab_types") or lab_list
        debug["document_detection"] = doc_info
        debug["lab_list_prioritized"] = lab_list

        sym_matches = detect_symptom_routes(user_text, extracted_symptoms or [])
        ctx.detected_symptom_groups = [m["route_id"] for m in sym_matches]
        debug["symptom_matches"] = sym_matches

        primary_lab_type: str | None = lab_list[0] if lab_list else None
        primary_lab_route: str | None = LAB_TYPE_TO_ROUTE.get(primary_lab_type) if primary_lab_type else None

        has_urinary_symptoms = any(
            m.get("route_id") == "urinary_route" and float(m.get("confidence") or 0) >= 0.65 for m in sym_matches
        )

        blocked: list[str] = []
        conflict_reasons: list[str] = []
        if primary_lab_route:
            b, r = apply_route_conflicts(
                primary_lab_route,
                ctx.detected_symptom_groups,
                has_strong_urinary_symptoms=has_urinary_symptoms,
            )
            blocked.extend(b)
            conflict_reasons.extend(r)

        secondary: list[str] = []
        for m in sym_matches:
            rid = m["route_id"]
            if rid in blocked:
                continue
            if rid != primary_lab_route and rid not in secondary:
                secondary.append(rid)

        if primary_lab_route:
            if len(lab_list) == 1:
                confidence = 0.9
            elif len(lab_list) == 2:
                confidence = 0.78
            else:
                confidence = 0.68
            reasons = [
                f"document_lab_primary:{primary_lab_type}(prioritized)",
                *conflict_reasons,
            ]
            return ClinicalRouteDecision(
                primary_route=primary_lab_route,
                secondary_routes=secondary[:3],
                blocked_routes=list(dict.fromkeys(blocked)),
                confidence=confidence,
                reasons=reasons,
                safety_override=False,
                debug={**debug, "lab_list": lab_list},
            )

        top_sym = sym_matches[0] if sym_matches else None
        if top_sym and float(top_sym.get("confidence") or 0) >= SYMPTOM_PRIMARY_MIN_CONFIDENCE:
            pr = top_sym["route_id"]
            reasons = [f"symptom_primary:{top_sym.get('reason')}"]
            return ClinicalRouteDecision(
                primary_route=pr,
                secondary_routes=[m["route_id"] for m in sym_matches[1:4] if m["route_id"] != pr],
                blocked_routes=list(dict.fromkeys(blocked)),
                confidence=float(top_sym["confidence"]),
                reasons=reasons,
                safety_override=False,
                debug=debug,
            )

        if parsed_documents:
            return ClinicalRouteDecision(
                primary_route="physician_report_only_route",
                secondary_routes=["generic_safe_route"],
                blocked_routes=[],
                confidence=0.42,
                reasons=["document_present_but_lab_type_unknown", "symptom_signal_below_threshold_for_branch_gating"],
                safety_override=False,
                debug=debug,
            )

        return ClinicalRouteDecision(
            primary_route="generic_safe_route",
            secondary_routes=[],
            blocked_routes=[],
            confidence=0.38,
            reasons=["low_confidence_fallback", "no_lab_route_and_no_strong_symptom_route"],
            safety_override=False,
            debug=debug,
        )


def route_to_lab_type_alias(primary_route: str) -> str | None:
    """Для совместимости с diagnosis_filter / lab_type (organic_acids, cbc, thyroid)."""
    inv = {v: k for k, v in LAB_TYPE_TO_ROUTE.items()}
    return inv.get(primary_route)


# ---------------------------------------------------------------------------
# Organic acids physician report — осевой routing (ranked_axes, user, doctor)
# ---------------------------------------------------------------------------


def _oa_s(x: Any) -> str:
    return str(x or "").strip()


def _oa_low(x: Any) -> str:
    return _oa_s(x).lower()


def _oa_to_float(x: Any) -> float:
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return 0.0


@dataclass
class RoutingAxis:
    key: str
    label: str
    score: float = 0.0
    evidence: List[str] = field(default_factory=list)

    def add(self, weight: float, evidence: str) -> None:
        self.score += float(weight)
        ev = _oa_s(evidence)
        if ev and ev not in self.evidence:
            self.evidence.append(ev)


def _abnormal_markers(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(report.get("abnormal_markers_table") or [])


def _group_rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(report.get("grouped_interpretation_table") or [])


def _hypothesis_rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(report.get("top_hypotheses_table") or [])


def _follow_rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(report.get("recommended_followup_table") or [])


def _contains_any(text: str, parts: List[str]) -> bool:
    low = _oa_low(text)
    return any(p in low for p in parts)


def _build_axes() -> Dict[str, RoutingAxis]:
    return {
        "energy": RoutingAxis("energy", "Энергетический обмен"),
        "beta_oxidation": RoutingAxis("beta_oxidation", "Жирные кислоты и β-окисление"),
        "cofactors": RoutingAxis("cofactors", "Кофакторные и витамин-зависимые маркеры"),
        "xenobiotics": RoutingAxis("xenobiotics", "Внешняя метаболическая нагрузка"),
        "glutathione": RoutingAxis("glutathione", "Окислительный стресс / глутатионовый контекст"),
        "nitrogen_cycle": RoutingAxis("nitrogen_cycle", "Азотистый обмен"),
        "other": RoutingAxis("other", "Прочие метаболические изменения"),
    }


def _domain_key_from_group_name(group: str) -> str:
    low = _oa_low(group)
    if "энерг" in low:
        return "energy"
    if "β-окис" in low or "жир" in low:
        return "beta_oxidation"
    if "витамин" in low or "кофактор" in low:
        return "cofactors"
    if "ксенобиот" in low or "внешняя метаболическая нагрузка" in low or "детокс" in low:
        return "xenobiotics"
    if "глутатион" in low or "окислительный стресс" in low:
        return "glutathione"
    if "азот" in low or "оротов" in low:
        return "nitrogen_cycle"
    return "other"


def _apply_group_signals(report: Dict[str, Any], axes: Dict[str, RoutingAxis]) -> None:
    for row in _group_rows(report):
        domain_key = _oa_s(row.get("domain_key")) or _domain_key_from_group_name(_oa_s(row.get("group")))
        label = _oa_s(row.get("group")) or axes.get(domain_key, RoutingAxis(domain_key, domain_key)).label
        markers = [_oa_s(x) for x in (row.get("markers") or []) if _oa_s(x)]
        evidence = f"{label}: {', '.join(markers[:4])}" if markers else label

        if domain_key not in axes:
            axes[domain_key] = RoutingAxis(domain_key, label or domain_key)

        weight = 2.8 + min(len(markers) * 0.35, 1.6)
        axes[domain_key].add(weight, evidence)


def _marker_severity(marker: Dict[str, Any]) -> float:
    flag = _oa_low(marker.get("flag"))
    value = _oa_to_float(marker.get("value"))
    ref_low = _oa_to_float(marker.get("ref_low"))
    ref_high = _oa_to_float(marker.get("ref_high"))

    if flag == "high":
        if ref_high <= 0:
            return max(value, 0.0)
        return max((value - ref_high) / max(abs(ref_high), 1e-6), 0.0)
    if flag == "low":
        if ref_low <= 0:
            return abs(value)
        return max((ref_low - value) / max(abs(ref_low), 1e-6), 0.0)
    return 0.0


def _apply_marker_signals(report: Dict[str, Any], axes: Dict[str, RoutingAxis]) -> None:
    for row in _abnormal_markers(report):
        name = _oa_s(row.get("name"))
        category = _oa_s(row.get("category"))
        low_name = _oa_low(name)
        sev = _marker_severity(row)
        evidence = f"{name} ({category}, {_oa_s(row.get('flag'))})"

        base_key = _domain_key_from_group_name(category)
        if base_key not in axes:
            axes[base_key] = RoutingAxis(base_key, category or base_key)
        axes[base_key].add(1.2 + min(sev * 2.5, 4.0), evidence)

        if _contains_any(low_name, ["малонов", "лактат", "пируват", "гидроксимасля", "ацетоуксус", "3-гидрокси-3-метилглутар"]):
            axes["energy"].add(1.3 + min(sev * 1.4, 2.5), evidence)

        if _contains_any(low_name, ["суберинов", "себацинов", "адипинов", "этилмалон"]):
            axes["beta_oxidation"].add(1.6 + min(sev * 1.5, 2.8), evidence)

        if _contains_any(low_name, ["пиколинов", "квинолинов", "формиминоглутам", "ксантурен", "метилмалон", "кинурен"]):
            axes["cofactors"].add(1.5 + min(sev * 1.4, 2.6), evidence)

        if _contains_any(low_name, ["метилгиппур", "миндальн", "гиппур", "бензойн", "трикарбал", "пара-гидроксибенз", "фенилглиокс"]):
            axes["xenobiotics"].add(1.6 + min(sev * 1.4, 2.6), evidence)

        if "пироглутам" in low_name:
            axes["glutathione"].add(1.5 + min(sev * 1.2, 2.2), evidence)

        if "оротов" in low_name:
            axes["nitrogen_cycle"].add(1.1 + min(sev * 1.1, 2.0), evidence)


def _apply_hypothesis_signals(report: Dict[str, Any], axes: Dict[str, RoutingAxis]) -> None:
    for row in _hypothesis_rows(report):
        hypo = _oa_s(row.get("hypothesis") if isinstance(row, dict) else row)
        low_h = _oa_low(hypo)
        if not hypo:
            continue

        if _contains_any(low_h, ["энергетического", "энергетический"]):
            axes["energy"].add(1.0, hypo)
        if _contains_any(low_h, ["жирового обмена", "жирных кислот", "β-окис"]):
            axes["beta_oxidation"].add(1.0, hypo)
        if _contains_any(low_h, ["витамин", "кофактор"]):
            axes["cofactors"].add(1.0, hypo)
        if _contains_any(low_h, ["внешней метаболической нагрузки", "экспозиции", "ксенобиот", "внешняя нагрузка"]):
            axes["xenobiotics"].add(1.0, hypo)
        if _contains_any(low_h, ["глутатион", "окислительный стресс"]):
            axes["glutathione"].add(0.9, hypo)
        if _contains_any(low_h, ["азотист", "оротов"]):
            axes["nitrogen_cycle"].add(0.8, hypo)


def _apply_followup_signals(report: Dict[str, Any], axes: Dict[str, RoutingAxis]) -> None:
    for row in _follow_rows(report):
        check = _oa_s(row.get("check"))
        why = _oa_s(row.get("why"))
        joined = f"{check} — {why}".strip(" —")
        low_joined = _oa_low(joined)
        if not joined:
            continue

        if _contains_any(low_joined, ["питания", "интервалы", "голодания", "глюкоза"]):
            axes["energy"].add(0.7, joined)
        if _contains_any(low_joined, ["дефицит", "витамин", "кофактор", "рацион"]):
            axes["cofactors"].add(0.7, joined)
        if _contains_any(low_joined, ["лекарства", "бады", "бытовые", "экспозиции", "среды", "химические"]):
            axes["xenobiotics"].add(0.7, joined)
        if _contains_any(low_joined, ["аммиак", "печёноч", "азотист"]):
            axes["nitrogen_cycle"].add(0.6, joined)
        if _contains_any(low_joined, ["нагрузка", "глутатион", "окислительный стресс"]):
            axes["glutathione"].add(0.6, joined)


def _rank_axes(axes: Dict[str, RoutingAxis]) -> List[RoutingAxis]:
    ranked = list(axes.values())
    ranked.sort(key=lambda x: x.score, reverse=True)
    return [x for x in ranked if x.score > 0]


def _severity_label(abnormal_count: int, top_score: float) -> str:
    if abnormal_count >= 10 or top_score >= 8.0:
        return "заметные изменения"
    if abnormal_count >= 4 or top_score >= 4.0:
        return "умеренные изменения"
    if abnormal_count >= 1:
        return "отдельные отклонения"
    return "значимых отклонений по распознанным данным не видно"


def _profile_phrase(ranked: List[RoutingAxis]) -> str:
    if not ranked:
        return "Профиль требует плановой клинической оценки."

    top = ranked[0].key
    second = ranked[1].key if len(ranked) > 1 else ""

    if top in {"energy", "beta_oxidation"} and second in {"energy", "beta_oxidation"}:
        return "Профиль в первую очередь выглядит как сочетание изменений энергетического и жирового обмена."
    if top == "cofactors":
        return "Профиль в первую очередь выглядит как паттерн возможной кофакторной или витаминной недостаточности."
    if top == "xenobiotics":
        return "Профиль в первую очередь выглядит как паттерн возможной внешней метаболической нагрузки."
    if top == "glutathione":
        return "Профиль в первую очередь выглядит как паттерн возможного окислительного стресса."
    if top == "nitrogen_cycle":
        return "Профиль требует осторожной оценки азотистого обмена."
    return "Профиль смешанный и требует клинической корреляции."


def _build_user_blocks(ranked: List[RoutingAxis], report: Dict[str, Any]) -> Dict[str, Any]:
    abnormal_count = len(_abnormal_markers(report))
    top_score = ranked[0].score if ranked else 0.0
    severity = _severity_label(abnormal_count, top_score)

    headline = f"В профиле органических кислот есть {severity}: {abnormal_count} значимых отклонений среди распознанных маркеров."

    what_found: List[str] = []
    for axis in ranked[:3]:
        what_found.append(f"Главная зона внимания — {axis.label.lower()}.")

    meaning: List[str] = []
    for axis in ranked[:3]:
        if axis.key == "energy":
            meaning.append("Это может быть связано с тем, как организм получает и использует энергию.")
        elif axis.key == "beta_oxidation":
            meaning.append("Есть сигналы, которые врач может оценивать в контексте обмена жиров.")
        elif axis.key == "cofactors":
            meaning.append("Есть неспецифичные признаки возможного дефицита витаминов или кофакторов.")
        elif axis.key == "xenobiotics":
            meaning.append("Часть показателей может зависеть от внешних факторов: питания, лекарств, БАДов, бытовой химии.")
        elif axis.key == "glutathione":
            meaning.append("Есть отдельный сигнал возможного окислительного стресса.")
        elif axis.key == "nitrogen_cycle":
            meaning.append("Некоторые показатели требуют осторожной оценки азотистого обмена.")

    next_steps = ["Показать результат лечащему врачу или педиатру."]
    axis_keys = {x.key for x in ranked[:4]}
    if "energy" in axis_keys or "beta_oxidation" in axis_keys:
        next_steps.append("Вспомнить режим питания: были ли большие интервалы между едой, снижение аппетита, ограничения в рационе.")
    if "cofactors" in axis_keys:
        next_steps.append("Обсудить с врачом, нужен ли контроль дефицитных состояний и оценка рациона.")
    if "xenobiotics" in axis_keys:
        next_steps.append("Сообщить врачу о лекарствах, БАДах и возможных внешних воздействиях.")

    reassurance = "Сам по себе этот анализ не устанавливает диагноз. Он помогает понять, в какую сторону смотреть дальше."
    urgent = (
        "Срочно обращаться за помощью нужно не из-за самого анализа, а если есть опасные симптомы: "
        "сильная слабость, повторная рвота, обезвоживание, судороги, нарушение сознания, резкое ухудшение состояния, "
        "сильная боль в животе или одышка."
    )

    summary_text = " ".join([
        headline,
        what_found[0] if what_found else "",
        meaning[0] if meaning else "",
        reassurance,
    ]).strip()

    return {
        "display_summary": headline,
        "user_summary": summary_text,
        "safe_next_steps": " ".join(next_steps).strip(),
        "when_urgent": urgent,
        "user_report_text": summary_text,
        "user_report_structured": {
            "severity": "normal",
            "headline": headline,
            "blocks": [
                {"title": "Что видно по анализу", "items": what_found or ["Есть отклонения, которые требуют клинической оценки."]},
                {"title": "Что это может значить простыми словами", "items": meaning or [reassurance]},
                {"title": "Что делать дальше", "items": next_steps},
                {"title": "Важно понимать", "items": [reassurance]},
            ],
        },
    }


def _build_doctor_synthesis(ranked: List[RoutingAxis], report: Dict[str, Any]) -> Dict[str, Any]:
    top_lines: List[str] = []
    for axis in ranked[:4]:
        if not axis.evidence:
            top_lines.append(f"{axis.label}: score={axis.score:.1f}")
        else:
            top_lines.append(f"{axis.label}: {', '.join(axis.evidence[:3])}")

    case_summary_parts: List[str] = []
    if ranked:
        case_summary_parts.append(
            "Приоритетные оси интерпретации: " + ", ".join(x.label for x in ranked[:3]) + "."
        )
    case_summary_parts.append(
        f"Число значимых отклонений среди надёжно интерпретируемых маркеров: {len(_abnormal_markers(report))}."
    )
    case_summary_parts.append(_profile_phrase(ranked))
    case_summary_parts.append("Требуется клиническая корреляция с жалобами, питанием и анамнезом.")

    conclusions = []
    for axis in ranked[:4]:
        marker_hint = f" ({', '.join(axis.evidence[:2])})" if axis.evidence else ""
        conclusions.append(f"{axis.label}: score {axis.score:.1f}{marker_hint}")

    return {
        "routing_top_lines": top_lines,
        "routing_case_summary": " ".join(case_summary_parts).strip(),
        "routing_conclusions": conclusions,
    }


def build_clinical_routing_output(report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Главный routing-слой для organic acids physician report.
    Возвращает:
    - ranked_axes
    - user-facing synthesis
    - doctor-facing synthesis
    """
    axes = _build_axes()

    _apply_group_signals(report, axes)
    _apply_marker_signals(report, axes)
    _apply_hypothesis_signals(report, axes)
    _apply_followup_signals(report, axes)

    ranked = _rank_axes(axes)

    user_part = _build_user_blocks(ranked, report)
    doctor_part = _build_doctor_synthesis(ranked, report)

    ranked_serialized = [
        {
            "key": x.key,
            "label": x.label,
            "score": round(x.score, 2),
            "evidence": x.evidence[:6],
        }
        for x in ranked[:6]
    ]

    return {
        "ranked_axes": ranked_serialized,
        "user": user_part,
        "doctor": doctor_part,
    }
