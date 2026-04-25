from __future__ import annotations

from typing import Any, Dict, List

from app.services.organic_acids_commentary_templates import build_followup_comment


def _s(x: Any) -> str:
    return str(x or "").strip()


def _low(x: Any) -> str:
    return _s(x).lower()


def _to_float(x: Any) -> float:
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return 0.0


def _severity_score(marker: Dict[str, Any]) -> float:
    flag = _low(marker.get("flag"))
    value = _to_float(marker.get("value"))
    ref_low = _to_float(marker.get("ref_low"))
    ref_high = _to_float(marker.get("ref_high"))

    if flag == "high":
        if ref_high <= 0:
            return max(value, 0.0)
        return max(0.0, (value - ref_high) / max(abs(ref_high), 1e-6))
    if flag == "low":
        if ref_low <= 0:
            return abs(value)
        return max(0.0, (ref_low - value) / max(abs(ref_low), 1e-6))
    return 0.0


def _domain_key_from_group(group: str) -> str:
    low = _low(group)
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


def _domain_label(key: str, fallback: str = "") -> str:
    mapping = {
        "energy": "Энергетический обмен",
        "beta_oxidation": "Жирные кислоты и β-окисление",
        "cofactors": "Кофакторные и витамин-зависимые маркеры",
        "xenobiotics": "Внешняя метаболическая нагрузка",
        "glutathione": "Окислительный стресс / глутатионовый контекст",
        "nitrogen_cycle": "Азотистый обмен",
        "other": "Прочие метаболические изменения",
    }
    return mapping.get(key, fallback or key or "Прочие метаболические изменения")


def build_clinical_scores(
    abnormal_markers: List[Dict[str, Any]],
    groups: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Считает силу основных метаболических доменов.
    На входе:
    - abnormal_markers: уже отфильтрованные и надёжные отклонения
    - groups: domain interpretations

    На выходе:
    - phenotype
    - ranked_domains
    - dominant_axes
    """
    domain_scores: Dict[str, Dict[str, Any]] = {}

    # 1. Вклад готовых групп
    for group in groups or []:
        group_name = _s(group.get("group"))
        domain_key = _s(group.get("domain_key")) or _domain_key_from_group(group_name)
        marker_names = [_s(x) for x in (group.get("markers") or []) if _s(x)]

        if domain_key not in domain_scores:
            domain_scores[domain_key] = {
                "key": domain_key,
                "label": _domain_label(domain_key, group_name),
                "score": 0.0,
                "marker_count": 0,
                "top_markers": [],
            }

        domain_scores[domain_key]["score"] += 2.2 + min(len(marker_names) * 0.35, 2.0)
        domain_scores[domain_key]["marker_count"] += len(marker_names)

        for name in marker_names[:5]:
            if name not in domain_scores[domain_key]["top_markers"]:
                domain_scores[domain_key]["top_markers"].append(name)

    # 2. Вклад конкретных маркеров
    for marker in abnormal_markers or []:
        name = _s(marker.get("name"))
        category = _s(marker.get("category"))
        sev = _severity_score(marker)

        domain_key = _domain_key_from_group(category)
        if domain_key not in domain_scores:
            domain_scores[domain_key] = {
                "key": domain_key,
                "label": _domain_label(domain_key, category),
                "score": 0.0,
                "marker_count": 0,
                "top_markers": [],
            }

        domain_scores[domain_key]["score"] += 1.1 + min(sev * 2.8, 5.5)
        domain_scores[domain_key]["marker_count"] += 1

        if name and name not in domain_scores[domain_key]["top_markers"]:
            domain_scores[domain_key]["top_markers"].append(name)

    ranked = sorted(domain_scores.values(), key=lambda x: x["score"], reverse=True)

    phenotype = "mixed"
    if ranked:
        top = ranked[0]["key"]
        if top == "energy":
            phenotype = "energy_shift"
        elif top == "beta_oxidation":
            phenotype = "fat_metabolism_shift"
        elif top == "cofactors":
            phenotype = "cofactor_deficit_pattern"
        elif top == "xenobiotics":
            phenotype = "external_load_pattern"
        elif top == "glutathione":
            phenotype = "oxidative_stress_pattern"
        elif top == "nitrogen_cycle":
            phenotype = "nitrogen_context_pattern"

    dominant_axes = ranked[:3]

    return {
        "phenotype": phenotype,
        "ranked_domains": ranked,
        "dominant_axes": dominant_axes,
    }


def build_scored_summary(
    abnormal_markers: List[Dict[str, Any]],
    clinical_scores: Dict[str, Any],
) -> List[str]:
    abnormal_count = len(abnormal_markers or [])
    dominant = clinical_scores.get("dominant_axes") or []

    lines: List[str] = []

    if dominant:
        labels = [str(x.get("label") or "").strip() for x in dominant if str(x.get("label") or "").strip()]
        if labels:
            lines.append("Наиболее выраженные изменения относятся к следующим осям: " + ", ".join(labels) + ".")

    if abnormal_count >= 1 and abnormal_markers:
        top_names = [str(m.get("name") or "—").strip() for m in abnormal_markers[:8] if m.get("name")]
        if top_names:
            lines.append(
                "Места отклонений от нормы (маркеры): " + ", ".join(top_names) + "."
                + (" Список не полный; в отчёте приведены все распознанные отклонения." if abnormal_count > 8 else "")
            )

    if abnormal_count >= 10:
        lines.append("Есть выраженные изменения метаболического профиля; рекомендуется расширенная диагностика и коррекция под контролем врача.")
    elif abnormal_count >= 4:
        lines.append("Есть умеренные изменения, требующие клинической оценки, дообследования по показаниям и коррекции питания/добавок по назначению.")
    elif abnormal_count >= 1:
        lines.append("Есть отдельные отклонения, требующие плановой оценки и при необходимости — диагностики, лечения, коррекции питания и добавок.")
    else:
        lines.append("По распознанным данным значимых отклонений не выявлено.")

    phenotype = str(clinical_scores.get("phenotype") or "")
    phenotype_map = {
        "energy_shift": "Профиль может соответствовать сдвигу энергетического обмена. Клиническая значимость и направления коррекции определяются после очной оценки.",
        "fat_metabolism_shift": "Профиль может соответствовать сдвигу обмена жирных кислот. При подтверждении контекста дальнейшие шаги — по назначению врача.",
        "cofactor_deficit_pattern": "Профиль может соответствовать паттерну кофакторной/витаминной недостаточности. Подтверждение и любые рекомендации — только после очной оценки.",
        "external_load_pattern": "Профиль может соответствовать внешней метаболической нагрузке. Анализ экспозиций и возможные направления коррекции — в рамках консультации врача.",
        "oxidative_stress_pattern": "Профиль может соответствовать паттерну окислительного стресса. Интерпретация и при необходимости коррекция — по назначению врача после подтверждения контекста.",
        "nitrogen_context_pattern": "Профиль требует осторожной оценки азотистого обмена. Дообследование и любые рекомендации — только по назначению врача.",
        "mixed": "Профиль смешанный; требует клинической корреляции. Дообследование и направления коррекции — по результатам очной консультации.",
    }
    if phenotype in phenotype_map:
        lines.append(phenotype_map[phenotype])

    lines.append("Этот анализ не устанавливает диагноз изолированно и должен оцениваться вместе с жалобами и анамнезом. Диагностика, лечение и коррекция — только по назначению врача.")
    return lines[:6]


def build_scored_followup(
    clinical_scores: Dict[str, Any],
) -> List[Dict[str, str]]:
    """
    Что делать дальше: разделение на (1) подтверждающие тесты, (2) очная оценка, (3) направления коррекции.
    Лечение/добавки/питание — только в отдельном блоке, формулировки «может обсуждаться с врачом», «после подтверждения», «не является назначением».
    """
    ranked = clinical_scores.get("ranked_domains") or []
    keys = [str(x.get("key") or "") for x in ranked[:4]]

    table: List[Dict[str, str]] = [
        {
            "direction": "Очная оценка",
            "check": "Лечащий врач / педиатр — интерпретация результатов, решение о дообследовании и дальнейших шагах",
            "why": "Клиническая значимость определяется только в рамках очной консультации с учётом жалоб и анамнеза",
            "priority": "высокий",
        }
    ]

    # Подтверждающие тесты / что уточнить — без назначений
    if "energy" in keys or "beta_oxidation" in keys:
        table.append(
            {
                "direction": "Что подтвердить (энергообмен)",
                "check": "При наличии показаний: глюкоза, ОГТТ, лактат натощак; оценка режима питания и переносимости голодания — по назначению врача",
                "why": "Уточнить вклад углеводного и жирового обмена",
                "priority": "средний",
            }
        )

    if "cofactors" in keys:
        table.append(
            {
                "direction": "Что подтвердить (кофакторы)",
                "check": "Обязательно: B12, фолат (фолиевая кислота), гомоцистеин. Желательно по показаниям: ферритин, витамин D, глюкоза/инсулин. При метилмалоновой ↑ — B12 и при необходимости метилмалоновая кислота в крови. Всё по назначению врача.",
                "why": "Подтверждение контекста перед любыми рекомендациями по коррекции",
                "priority": "средний",
            }
        )

    if "xenobiotics" in keys:
        table.append(
            {
                "direction": "Что уточнить (экспозиции)",
                "check": "Анализ лекарств, БАДов, бытовой химии и рациона в рамках очной консультации",
                "why": "Оценка возможной внешней нагрузки",
                "priority": "средний",
            }
        )

    if "glutathione" in keys:
        table.append(
            {
                "direction": "Что подтвердить (окислительный стресс)",
                "check": "Клинический контекст; при необходимости — дообследование по назначению врача",
                "why": "Интерпретация маркера в комплексе с другими данными",
                "priority": "средний",
            }
        )

    if "nitrogen_cycle" in keys:
        table.append(
            {
                "direction": "Что подтвердить (азотистый обмен)",
                "check": "По назначению врача: аммиак, печёночные пробы; при необходимости — генетика",
                "why": "Оценка цикла мочевины и печёночной функции",
                "priority": "средний",
            }
        )

    table.append(
        {
            "direction": "Контроль в динамике",
            "check": "Повторная оценка при наличии клинических оснований — по решению врача",
            "why": "Понять, стойкие ли изменения",
            "priority": "средний",
        }
    )

    # Отдельный блок: направления коррекции — только «может обсуждаться», не назначение
    table.append(
        {
            "direction": "Потенциальные направления коррекции",
            "check": "Питание, образ жизни, нутритивная поддержка могут обсуждаться с врачом после очной оценки и при подтверждении контекста. Не являются назначением.",
            "why": "Любые рекомендации по добавкам или лечению — только по назначению врача после клинического подтверждения",
            "priority": "средний",
        }
    )

    for row in table:
        row["why"] = build_followup_comment(direction=row.get("direction", ""), check=row.get("check", ""))

    return table[:10]
