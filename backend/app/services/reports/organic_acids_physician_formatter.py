"""
Премиальный formatter physician report для organic acids.
Логика:
- фильтр подозрительных значений
- доменные группы
- clinical scoring
- patient type profile
- профессиональные комментарии к маркерам и группам
- компактный clinical summary
- приоритизация top findings
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.filters.organic_acids_hypothesis_filter import (
    filter_organic_acids_hypotheses,
)
from app.services.organic_acids_rules import (
    build_domain_interpretations,
    build_rule_based_hypotheses,
    is_suspicious_reference,
)
from app.services.organic_acids_scoring import (
    build_clinical_scores,
    build_scored_followup,
    build_scored_summary,
)
from app.services.organic_acids_patient_type_engine import (
    build_patient_type_profile,
    build_patient_type_summary,
)
from app.services.organic_acids_commentary_templates import (
    build_marker_comment,
    build_group_interpretation,
    build_hypothesis_comment,
    build_followup_comment,
    build_possible_correction_directions,
    build_expanded_correction_directions_flat,
    build_pattern_narrative,
    build_recommendation_blocks,
)
from app.services.correction_block_generator import (
    generate_correction_block,
    markers_from_report,
)


def _to_float(x: Any) -> float:
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return 0.0


def _sort_abnormal(markers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def severity_score(x: Dict[str, Any]) -> float:
        flag = str(x.get("flag", "")).lower()
        value = _to_float(x.get("value"))
        ref_low = _to_float(x.get("ref_low"))
        ref_high = _to_float(x.get("ref_high"))

        if flag == "high":
            if ref_high <= 0:
                return value
            return (value - ref_high) / max(abs(ref_high), 1e-6)
        if flag == "low":
            if ref_low <= 0:
                return abs(value)
            return (ref_low - value) / max(abs(ref_low), 1e-6)
        return 0.0

    return sorted(markers or [], key=severity_score, reverse=True)


def _clean_note(note: Any) -> str:
    s = str(note or "").strip()
    return s


def _build_limitations(
    source_limitations: List[Any],
    quality_notes: List[Any],
    suspicious_markers: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    for x in list(source_limitations or []) + list(quality_notes or []):
        if isinstance(x, dict):
            rows.append(
                {
                    "limitation": str(x.get("limitation") or x.get("title") or "Ограничение"),
                    "value": str(x.get("value") or "—"),
                }
            )
        else:
            rows.append({"limitation": str(x), "value": "—"})

    if suspicious_markers:
        bad_names = ", ".join(str(x.get("name") or "—") for x in suspicious_markers[:5])
        rows.append(
            {
                "limitation": "Часть маркеров имела подозрительные референсы или признаки OCR-ошибки",
                "value": bad_names or "—",
            }
        )

    dedup: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        key = (
            str(row.get("limitation") or "").strip().lower(),
            str(row.get("value") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        dedup.append(row)

    return dedup[:10]


def _build_doc_summary(parsed: Dict[str, Any]) -> Dict[str, Any]:
    patient = parsed.get("patient") or {}
    return {
        "doc_type": parsed.get("doc_type", "organic_acids_urine"),
        "sex": patient.get("sex", "—"),
        "age_years": patient.get("age_years", "—"),
        "sample_type": patient.get("sample_type", "—"),
        "collection_date": patient.get("collection_date", "—"),
        "report_date": patient.get("report_date", "—"),
    }


def _compact_groups(groups: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for g in groups[:limit]:
        marker_names = list(g.get("markers") or [])[:8]
        group_name = str(g.get("group") or "").strip()
        out.append(
            {
                "group": group_name,
                "markers": marker_names,
                "interpretation": build_group_interpretation(
                    group_name=group_name,
                    marker_names=marker_names,
                ),
                "domain_key": g.get("domain_key"),
                "count": g.get("count", len(marker_names)),
                "possible_correction_directions": build_possible_correction_directions(
                    domain_key=str(g.get("domain_key") or ""),
                ),
            }
        )
    return out


def _build_hypotheses_table(
    reliable_markers: List[Dict[str, Any]],
    raw_hypotheses: List[str] | None = None,
) -> List[Dict[str, Any]]:
    rule_hypos = build_rule_based_hypotheses(reliable_markers)
    merged_names: List[str] = [h["hypothesis"] for h in rule_hypos]

    hypo_result = filter_organic_acids_hypotheses(
        (raw_hypotheses or []) + merged_names,
        max_total=5,
        max_summary=3,
    )
    filtered = hypo_result.get("filtered") or []

    rule_map = {h["hypothesis"]: h for h in rule_hypos}
    out: List[Dict[str, Any]] = []

    for name in filtered[:5]:
        item = rule_map.get(name)
        if item:
            out.append(
                {
                    "hypothesis": item["hypothesis"],
                    "basis": "Rule-based pattern across organic acids markers",
                    "confidence": item["confidence"],
                    "comment": build_hypothesis_comment(hypothesis=item["hypothesis"]),
                }
            )
        else:
            out.append(
                {
                    "hypothesis": str(name),
                    "basis": "Pattern across organic acids markers",
                    "confidence": "low",
                    "comment": build_hypothesis_comment(hypothesis=str(name)),
                }
            )
    return out


def _map_marker_to_group_name(marker_name: str, groups: List[Dict[str, Any]], fallback: str) -> str:
    for g in groups or []:
        names = set(str(x) for x in (g.get("markers") or []))
        if str(marker_name) in names:
            return str(g.get("group") or fallback)
    return fallback


def _enrich_categories(markers: List[Dict[str, Any]], groups: List[Dict[str, Any]]) -> None:
    """Проставляет category на маркерах по группам для build_clinical_scores."""
    for m in markers or []:
        m["category"] = _map_marker_to_group_name(
            str(m.get("name") or ""),
            groups,
            str(m.get("category") or "Прочие метаболические маркеры"),
        )


def _build_abnormal_table(
    reliable_abnormal: List[Dict[str, Any]],
    groups: List[Dict[str, Any]],
    limit: int = 10,
) -> List[Dict[str, Any]]:
    table: List[Dict[str, Any]] = []
    for m in reliable_abnormal[:limit]:
        group_name = _map_marker_to_group_name(
            marker_name=str(m.get("name") or ""),
            groups=groups,
            fallback=str(m.get("category") or "Прочие метаболические маркеры"),
        )
        source_note = _clean_note(m.get("comment") or m.get("note") or "")
        table.append(
            {
                "name": m.get("name"),
                "category": group_name,
                "value": m.get("value"),
                "ref_low": m.get("ref_low"),
                "ref_high": m.get("ref_high"),
                "flag": m.get("flag"),
                "comment": build_marker_comment(
                    marker_name=str(m.get("name") or ""),
                    flag=str(m.get("flag") or ""),
                    group_name=group_name,
                    source_note=source_note,
                ),
            }
        )
    return table


def _build_borderline_table(
    reliable_borderline: List[Dict[str, Any]],
    groups: List[Dict[str, Any]],
    limit: int = 8,
) -> List[Dict[str, Any]]:
    table: List[Dict[str, Any]] = []
    for m in reliable_borderline[:limit]:
        group_name = _map_marker_to_group_name(
            marker_name=str(m.get("name") or ""),
            groups=groups,
            fallback=str(m.get("category") or "Прочие метаболические маркеры"),
        )
        source_note = _clean_note(m.get("comment") or m.get("note") or "")
        table.append(
            {
                "name": m.get("name"),
                "category": group_name,
                "value": m.get("value"),
                "ref_low": m.get("ref_low"),
                "ref_high": m.get("ref_high"),
                "flag": m.get("flag"),
                "comment": build_marker_comment(
                    marker_name=str(m.get("name") or ""),
                    flag=str(m.get("flag") or ""),
                    group_name=group_name,
                    source_note=source_note,
                ),
            }
        )
    return table


def _dedup_lines(lines: List[str], limit: int = 5) -> List[str]:
    out: List[str] = []
    seen = set()
    for line in lines:
        s = str(line or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _enrich_followup_table(follow_table: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in follow_table or []:
        direction = str(row.get("direction") or "").strip()
        check = str(row.get("check") or "").strip()
        why = str(row.get("why") or "").strip()
        comment = build_followup_comment(direction=direction, check=check)

        if comment and comment.lower() not in why.lower():
            why = (why + " " + comment).strip() if why else comment

        out.append(
            {
                "direction": direction,
                "check": check,
                "why": why,
                "priority": str(row.get("priority") or "").strip(),
            }
        )
    return out[:8]


def _build_clinical_correction_block(groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Развёрнутые направления коррекции: список блоков { title, what_it_means, recommended }.
    Если развёрнутых блоков нет — fallback на короткие строки для обратной совместимости.
    """
    expanded = build_expanded_correction_directions_flat(groups)
    if expanded:
        return expanded
    items: List[Dict[str, Any]] = []
    seen = set()
    for group in groups[:4]:
        domain_key = str(group.get("domain_key") or "")
        for line in build_possible_correction_directions(domain_key=domain_key):
            s = str(line or "").strip()
            if not s or s.lower() in seen:
                continue
            seen.add(s.lower())
            items.append({"title": "", "what_it_means": "", "recommended": [s]})
            if len(items) >= 8:
                return items
    return items


def format_organic_acids_physician_report(
    parsed: Dict[str, Any],
    raw_hypotheses: List[str] | None = None,
) -> Dict[str, Any]:
    markers = parsed.get("markers") or []
    source_limitations = parsed.get("source_limitations") or []
    quality_notes = parsed.get("quality_notes") or []

    abnormal_all = [
        m for m in markers
        if str(m.get("flag", "")).lower() in ("high", "low")
    ]
    borderline_all = [
        m for m in markers
        if "near" in str(m.get("flag", "")).lower()
        or "border" in str(m.get("flag", "")).lower()
    ]

    suspicious_markers = [
        m for m in (abnormal_all + borderline_all)
        if is_suspicious_reference(m)
    ]
    reliable_abnormal = [
        m for m in abnormal_all
        if not is_suspicious_reference(m)
    ]
    reliable_borderline = [
        m for m in borderline_all
        if not is_suspicious_reference(m)
    ]

    reliable_abnormal = _sort_abnormal(reliable_abnormal)

    # Сохраняем исходную note/comment для шаблонов, но не даём ей стать финальным текстом 1-в-1
    for m in reliable_abnormal + reliable_borderline:
        m["comment"] = _clean_note(m.get("comment") or m.get("note") or "")

    raw_groups = build_domain_interpretations(reliable_abnormal + reliable_borderline)
    groups = _compact_groups(raw_groups, limit=5)
    _enrich_categories(reliable_abnormal, groups)
    _enrich_categories(reliable_borderline, groups)

    clinical_scores = build_clinical_scores(reliable_abnormal, groups)
    patient_type = build_patient_type_profile(reliable_abnormal, clinical_scores)

    scored_summary = build_scored_summary(reliable_abnormal, clinical_scores)
    patient_type_summary = build_patient_type_summary(patient_type)

    pattern_narrative = build_pattern_narrative(clinical_scores)
    recommendation_blocks = build_recommendation_blocks(clinical_scores)

    summary_lines = _dedup_lines(
        pattern_narrative + patient_type_summary + scored_summary, limit=10
    )

    follow_table = _enrich_followup_table(build_scored_followup(clinical_scores))
    hypo_table = _build_hypotheses_table(reliable_abnormal + reliable_borderline, raw_hypotheses)
    limitations = _build_limitations(source_limitations, quality_notes, suspicious_markers)

    triage_level = "routine"
    phenotype = str(clinical_scores.get("phenotype") or "")
    if phenotype == "nitrogen_context_pattern":
        triage_level = "planned_review"

    abnormal_table = _build_abnormal_table(reliable_abnormal, groups, limit=10)
    borderline_table = _build_borderline_table(reliable_borderline, groups, limit=8)

    report_draft = {
        "clinical_scores": clinical_scores,
        "abnormal_markers_table": abnormal_table,
        "grouped_interpretation_table": groups,
        "document_summary": _build_doc_summary(parsed),
    }
    markers = markers_from_report(report_draft)
    auto_correction = generate_correction_block(markers)
    correction_directions = (
        auto_correction if auto_correction else _build_clinical_correction_block(groups)
    )

    return {
        "report_type": "physician_report",
        "doc_type": "organic_acids_urine",
        "document_summary": _build_doc_summary(parsed),
        "abnormal_markers_table": abnormal_table,
        "borderline_markers_table": borderline_table,
        "grouped_interpretation_table": groups,
        "top_hypotheses_table": hypo_table,
        "recommended_followup_table": follow_table,
        "limitations": limitations,
        "summary": summary_lines,
        "triage": {
            "level": triage_level,
            "note": "Плановая клиническая интерпретация",
        },
        "clinical_scores": clinical_scores,
        "patient_type_profile": patient_type,
        "possible_correction_directions": correction_directions,
        "pattern_narrative": pattern_narrative,
        "recommendation_blocks": recommendation_blocks,
    }
