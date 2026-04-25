from __future__ import annotations

from typing import Any, Dict, List


def _s(x: Any) -> str:
    return str(x or "").strip()


def _safe_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        try:
            return float(str(x).replace(",", "."))
        except Exception:
            return 0.0


def _dominant_keys(clinical_scores: Dict[str, Any]) -> List[str]:
    ranked = clinical_scores.get("ranked_domains") or []
    out: List[str] = []
    for item in ranked[:4]:
        key = _s(item.get("key"))
        if key:
            out.append(key)
    return out


def _top_score(clinical_scores: Dict[str, Any]) -> float:
    ranked = clinical_scores.get("ranked_domains") or []
    if not ranked:
        return 0.0
    return _safe_float(ranked[0].get("score"))


def _second_score(clinical_scores: Dict[str, Any]) -> float:
    ranked = clinical_scores.get("ranked_domains") or []
    if len(ranked) < 2:
        return 0.0
    return _safe_float(ranked[1].get("score"))


def _domain_label(key: str) -> str:
    mapping = {
        "energy": "энергетического обмена",
        "beta_oxidation": "обмена жирных кислот",
        "cofactors": "кофакторно-витаминного статуса",
        "xenobiotics": "внешней метаболической нагрузки",
        "glutathione": "окислительного стресса",
        "nitrogen_cycle": "азотистого обмена",
        "other": "неспецифических метаболических изменений",
    }
    return mapping.get(key, key or "метаболических изменений")


def _axes_labels(keys: List[str]) -> List[str]:
    return [_domain_label(k) for k in keys if k]


def build_patient_type_profile(
    abnormal_markers: List[Dict[str, Any]],
    clinical_scores: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Возвращает тип профиля пациента по organic acids.
    Совместим с formatter/scoring слоями:
    - abnormal_markers: список надёжных abnormal markers
    - clinical_scores: результат build_clinical_scores(...)
    """
    abnormal_count = len(abnormal_markers or [])
    keys = _dominant_keys(clinical_scores)
    top = keys[0] if keys else "other"
    second = keys[1] if len(keys) > 1 else ""
    top_score = _top_score(clinical_scores)
    second_score = _second_score(clinical_scores)

    profile_key = "mixed_metabolic"
    profile_title = "Смешанный метаболический профиль"
    profile_description = "Есть несколько разнонаправленных осей изменений, которые требуют клинической корреляции."

    # 1. Выраженно доминирующий профиль
    if top and top_score >= max(second_score * 1.35, 3.5):
        if top == "energy":
            profile_key = "energy_dominant"
            profile_title = "Профиль с доминированием энергетического обмена"
            profile_description = "На первый план выходят маркеры, связанные с тем, как организм получает и использует энергию."
        elif top == "beta_oxidation":
            profile_key = "fat_metabolism_dominant"
            profile_title = "Профиль с доминированием обмена жирных кислот"
            profile_description = "На первый план выходят маркеры, связанные с жировым обменом и β-окислением."
        elif top == "cofactors":
            profile_key = "cofactor_deficit_dominant"
            profile_title = "Кофакторно-дефицитный профиль"
            profile_description = "На первый план выходят маркеры, которые врач может оценивать в контексте витаминных и кофакторных дефицитов."
        elif top == "xenobiotics":
            profile_key = "external_load_dominant"
            profile_title = "Профиль внешней метаболической нагрузки"
            profile_description = "На первый план выходят маркеры, которые могут зависеть от внешних факторов: питания, лекарств, БАДов, бытовой химии."
        elif top == "glutathione":
            profile_key = "oxidative_stress_dominant"
            profile_title = "Профиль возможного окислительного стресса"
            profile_description = "На первый план выходит сигнал, который может быть связан с антиоксидантной защитой и глутатионовым обменом."
        elif top == "nitrogen_cycle":
            profile_key = "nitrogen_context_dominant"
            profile_title = "Профиль с акцентом на азотистый обмен"
            profile_description = "На первый план выходит контекст азотистого обмена, который требует осторожной клинической оценки."

    # 2. Смешанные, но клинически читаемые паттерны
    elif top in {"energy", "beta_oxidation"} and second in {"energy", "beta_oxidation"}:
        profile_key = "energy_fat_mixed"
        profile_title = "Смешанный профиль энергетического и жирового обмена"
        profile_description = "Основные изменения относятся к энергетическому обмену и обмену жирных кислот."
    elif top in {"cofactors", "energy"} and second in {"cofactors", "energy", "beta_oxidation"}:
        profile_key = "energy_cofactor_mixed"
        profile_title = "Смешанный энергетико-кофакторный профиль"
        profile_description = "Есть сочетание изменений по энергетическому обмену и возможным витаминно-коферментным факторам."
    elif top == "xenobiotics" and second in {"glutathione", "cofactors", "energy", "beta_oxidation"}:
        profile_key = "external_load_mixed"
        profile_title = "Смешанный профиль внешней нагрузки"
        profile_description = "Есть признаки возможной внешней метаболической нагрузки в сочетании с внутренними метаболическими сдвигами."
    elif top == "glutathione" and second in {"xenobiotics", "cofactors"}:
        profile_key = "oxidative_mixed"
        profile_title = "Смешанный оксидативно-нагрузочный профиль"
        profile_description = "Есть сочетание признаков возможного окислительного стресса и внешней или дефицитной нагрузки."

    # 3. Выраженность профиля
    severity_label = "ограниченный"
    if abnormal_count >= 10 or top_score >= 8:
        severity_label = "выраженный"
    elif abnormal_count >= 4 or top_score >= 4:
        severity_label = "умеренный"

    dominant_axes = _axes_labels(keys[:3])

    return {
        "profile_key": profile_key,
        "profile_title": profile_title,
        "profile_description": profile_description,
        "severity_label": severity_label,
        "dominant_axes": dominant_axes,
        "abnormal_count": abnormal_count,
    }


def build_patient_type_summary(profile: Dict[str, Any]) -> List[str]:
    """
    Строит короткий summary-блок для formatter/report.
    Возвращает список строк, чтобы не ломать текущий pipeline.
    """
    title = _s(profile.get("profile_title"))
    desc = _s(profile.get("profile_description"))
    severity = _s(profile.get("severity_label"))
    axes = profile.get("dominant_axes") or []
    abnormal_count = profile.get("abnormal_count") or 0

    lines: List[str] = []

    if title:
        lines.append(f"По структуре отклонений это {severity} {title.lower()}.")
    if axes:
        lines.append("Основные оси: " + ", ".join(str(x) for x in axes[:3]) + ".")
    if abnormal_count:
        lines.append(f"Число значимых отклонений среди распознанных маркеров: {abnormal_count}.")
    if desc:
        lines.append(desc)

    return lines[:4]
