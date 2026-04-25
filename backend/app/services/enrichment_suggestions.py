"""Auto-suggest enrichment for weak complaints and cluster sprint planning."""
from __future__ import annotations

from typing import Any

from app.services.complaint_reference import get_complaint_by_name
from app.services.knowledge_flywheel import list_learning_candidates
from app.services.improvement_backlog import list_backlog
from app.services.complaint_draft_workflow import list_draft_candidates
from app.services.runtime_analytics import get_runtime_overview

_CLUSTER_DRAFTS = {
    "respiratory": {
        "symptoms": ["кашель", "боль в горле", "температура", "одышка", "слабость"],
        "anamnesis_questions": ["Когда начались симптомы?", "Есть ли температура или одышка?", "Кашель сухой или с мокротой?", "Был ли контакт с заболевшими?", "Что уже принимали?"],
        "red_flags": ["Одышка в покое", "Боль в груди", "Кровь в мокроте"],
        "suggested_labs": ["ОАК", "СРБ", "Пульсоксиметрия"],
        "nutrition_recommendations": ["Тёплое питьё", "Щадящее питание"],
        "physical_exercise_prevention_rehabilitation": ["Снизить нагрузку в острой фазе", "Постепенно вернуться к активности после улучшения"],
    },
    "gi": {
        "symptoms": ["боль в животе", "вздутие", "тошнота", "диарея или запор"],
        "anamnesis_questions": ["Где именно болит?", "Есть ли связь с едой?", "Есть ли рвота, температура, кровь?", "Что уже пробовали?", "Были ли такие эпизоды раньше?"],
        "red_flags": ["Кровь в стуле или рвоте", "Сильная постоянная боль в животе", "Признаки обезвоживания"],
        "suggested_labs": ["ОАК", "СРБ", "Копрограмма"],
        "nutrition_recommendations": ["Щадящее питание", "Регидратация при потере жидкости"],
        "physical_exercise_prevention_rehabilitation": ["До улучшения избегать интенсивной нагрузки"],
    },
    "neuro": {
        "symptoms": ["головная боль", "головокружение", "тошнота", "слабость"],
        "anamnesis_questions": ["Как давно симптом?", "Какой характер боли/головокружения?", "Есть ли нарушение речи, зрения, слабость?", "Есть ли температура или травма?", "Что помогает?"],
        "red_flags": ["Внезапная очень сильная головная боль", "Нарушение речи или слабость", "Потеря сознания"],
        "suggested_labs": ["ОАК", "СРБ", "Контроль давления"],
        "nutrition_recommendations": ["Достаточное питьё", "Не пропускать приёмы пищи"],
        "physical_exercise_prevention_rehabilitation": ["При остром симптоме снизить нагрузку", "После улучшения — мягкая активность"],
    },
}


def _merge_unique(base: list[str], extra: list[str], limit: int = 8) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for source in (base or []) + (extra or []):
        s = str(source or "").strip()
        if not s:
            continue
        low = s.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def complaint_enrichment_suggestion(complaint: str) -> dict[str, Any]:
    item = get_complaint_by_name(complaint) or {}
    name = str(item.get("complaint") or complaint or "").strip()
    analytics = get_runtime_overview(limit=5000)
    stats_rows = list(analytics.get("complaint_stats") or [])
    stat = next((x for x in stats_rows if str(x.get("complaint") or "").strip().lower() == name.lower()), {})
    approved_queue = [
        x
        for x in (list_learning_candidates(limit=1000) or [])
        if str(x.get("complaint") or x.get("chief_complaint") or "").strip().lower() == name.lower()
        and str(x.get("review_status") or "").strip().lower() == "approved"
    ]

    missing_sections: list[str] = []
    if len(item.get("symptoms") or []) < 4:
        missing_sections.append("symptoms")
    if len(item.get("anamnesis_questions") or []) < 5:
        missing_sections.append("anamnesis_questions")
    if len(item.get("red_flags") or []) < 3:
        missing_sections.append("red_flags")
    if len(item.get("suggested_labs") or []) < 3:
        missing_sections.append("suggested_labs")
    if len(item.get("nutrition_recommendations") or []) < 2:
        missing_sections.append("nutrition_recommendations")
    if len(item.get("physical_exercise_prevention_rehabilitation") or []) < 2:
        missing_sections.append("physical_exercise_prevention_rehabilitation")

    suggestions: list[str] = []
    if "symptoms" in missing_sections:
        suggestions.append("Расширить симптомы и типичную complaint-level картину.")
    if "anamnesis_questions" in missing_sections:
        suggestions.append("Добавить более точные вопросы для дифференцировки и next-best-question.")
    if "red_flags" in missing_sections:
        suggestions.append("Усилить red flags и emergency routing для этой жалобы.")
    if "suggested_labs" in missing_sections:
        suggestions.append("Добавить конкретные анализы и правила, когда их запрашивать.")
    if "nutrition_recommendations" in missing_sections or "physical_exercise_prevention_rehabilitation" in missing_sections:
        suggestions.append("Дописать питание, активность, профилактику и реабилитацию.")
    if int(stat.get("approved_cases") or 0) < 2:
        suggestions.append("Собрать и одобрить больше живых кейсов через review queue.")
    if float(stat.get("offline_share") or 0.0) < 0.5:
        suggestions.append("Усилить offline-first path и complaint protocol, чтобы снизить зависимость от LLM.")

    cluster = str(item.get("market_signal_cluster") or stat.get("cluster") or "")
    draft = _CLUSTER_DRAFTS.get(cluster, {})
    draft_entry = {
        "complaint": name,
        "category": str(item.get("category") or ""),
        "symptoms": _merge_unique(list(item.get("symptoms") or []), list(draft.get("symptoms") or [])),
        "anamnesis_questions": _merge_unique(list(item.get("anamnesis_questions") or []), list(draft.get("anamnesis_questions") or [])),
        "red_flags": _merge_unique(list(item.get("red_flags") or []), list(draft.get("red_flags") or []), limit=6),
        "suggested_labs": _merge_unique(list(item.get("suggested_labs") or []), list(draft.get("suggested_labs") or []), limit=6),
        "nutrition_recommendations": _merge_unique(list(item.get("nutrition_recommendations") or []), list(draft.get("nutrition_recommendations") or []), limit=4),
        "physical_exercise_prevention_rehabilitation": _merge_unique(list(item.get("physical_exercise_prevention_rehabilitation") or []), list(draft.get("physical_exercise_prevention_rehabilitation") or []), limit=4),
    }

    return {
        "complaint": name,
        "cluster": cluster,
        "quality_score": int(stat.get("quality_score") or 0),
        "maturity": str(stat.get("maturity") or ""),
        "offline_share": float(stat.get("offline_share") or 0.0),
        "approved_cases": int(stat.get("approved_cases") or 0),
        "missing_sections": missing_sections,
        "suggestions": suggestions,
        "public_source_basis": list(item.get("public_source_basis") or []),
        "approved_case_ids": [str(x.get("id") or "") for x in approved_queue[:5]],
        "draft_entry": draft_entry,
    }


def cluster_sprint_plan(cluster: str) -> dict[str, Any]:
    analytics = get_runtime_overview(limit=5000)
    roadmap_rows = list(analytics.get("cluster_roadmap") or [])
    row = next((x for x in roadmap_rows if str(x.get("cluster") or "") == str(cluster or "")), {})
    complaint_stats = [x for x in (analytics.get("complaint_stats") or []) if str(x.get("cluster") or "") == str(cluster or "")]
    weakest = sorted(complaint_stats, key=lambda x: int(x.get("quality_score") or 0))[:5]
    actions = [
        "Усилить complaint protocols и anamnesis questions для слабых жалоб кластера.",
        "Добавить approved cases из review queue в offline knowledge (export_reviewed_cases_to_knowledge).",
        "Проверить red flags и suggested labs для всех weak complaints кластера перед повышением offline share.",
        "Оценить, можно ли повысить offline share без потери safety: только при наличии red_flags и suggested_labs у кластера.",
    ]
    return {
        "cluster": str(cluster or ""),
        "avg_quality_score": float(row.get("avg_quality_score") or 0.0),
        "maturity": str(row.get("maturity") or ""),
        "offline_share": float(row.get("offline_share") or 0.0),
        "weakest_complaints": weakest,
        "next_actions": actions,
        "offline_share_safety_note": "Повышать offline share только после проверки red flags и suggested labs для всех weak complaints; иначе риск пропуска срочных случаев.",
    }


def cluster_workspace(cluster: str) -> dict[str, Any]:
    analytics = get_runtime_overview(limit=5000)
    sprint = cluster_sprint_plan(cluster)
    complaint_stats = [x for x in (analytics.get("complaint_stats") or []) if str(x.get("cluster") or "") == str(cluster or "")]
    backlog_items = [x for x in (list_backlog(limit=1000) or []) if str(x.get("cluster") or "") == str(cluster or "")]
    draft_candidates = list_draft_candidates(limit=1000, cluster=str(cluster or ""))
    approved_cases = [
        x
        for x in (list_learning_candidates(limit=1000) or [])
        if str(x.get("review_status") or "").strip().lower() == "approved"
        and str(x.get("protocol_source") or "") == "complaint"
        and str(x.get("complaint") or "").strip()
        and any(str(x.get("complaint") or "").strip().lower() == str(c.get("complaint") or "").strip().lower() for c in complaint_stats)
    ][:15]
    return {
        "cluster": str(cluster or ""),
        "summary": sprint,
        "complaints": complaint_stats,
        "backlog_items": backlog_items,
        "draft_candidates": draft_candidates,
        "approved_cases": approved_cases,
    }
