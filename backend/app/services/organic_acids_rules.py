from __future__ import annotations

from typing import Any, Dict, List

from app.services.organic_acids_commentary_templates import (
    build_group_interpretation,
    build_hypothesis_comment,
)


def normalize_marker_name(name: str) -> str:
    return str(name or "").strip().lower().replace("ё", "е")


def _to_float(x: Any) -> float | None:
    try:
        return float(x)
    except Exception:
        try:
            return float(str(x).replace(",", "."))
        except Exception:
            return None


def is_suspicious_reference(marker: Dict[str, Any]) -> bool:
    """
    Отсеиваем маркеры с подозрительными референсами / parse-ошибками,
    чтобы они не участвовали в reasoning/scoring/hypotheses.
    """
    name = normalize_marker_name(marker.get("name"))
    ref_low = _to_float(marker.get("ref_low"))
    ref_high = _to_float(marker.get("ref_high"))
    value = _to_float(marker.get("value"))

    if ref_low is None or ref_high is None or value is None:
        return True

    if ref_high <= ref_low:
        return True

    # Для organic acids отрицательная нижняя граница почти всегда выглядит подозрительно.
    if ref_low < 0:
        return True

    # Нереалистично широкий диапазон — обычно мусор OCR/парсинга.
    if (ref_high - ref_low) > 1000:
        return True

    if value < 0 and "кислот" in name:
        return True

    return False


def marker_domain(marker_name: str) -> str:
    """
    Категоризация маркеров по доменам.
    Важно: ключи должны совпадать с formatter/scoring/routing слоями.
    """
    n = normalize_marker_name(marker_name)

    # Энергетический обмен / углеводный контекст
    if any(k in n for k in [
        "малонов",
        "лактат",
        "пируват",
        "гидроксимасля",
        "ацетоуксус",
        "3-гидрокси-3-метилглутар",
    ]):
        return "energy"

    # Жирные кислоты / β-окисление
    if any(k in n for k in [
        "суберинов",
        "себацинов",
        "адипинов",
        "этилмалон",
    ]):
        return "beta_oxidation"

    # Кофакторные / витамин-зависимые / триптофановый путь
    if any(k in n for k in [
        "формиминоглутам",
        "пиколинов",
        "квинолинов",
        "ксантурен",
        "метилмалон",
        "кинурен",
    ]):
        return "cofactors"

    # Ксенобиотики / внешняя нагрузка
    if any(k in n for k in [
        "метилгиппур",
        "миндальн",
        "бензойн",
        "трикарбал",
        "гиппур",
        "пара-гидроксибенз",
        "парагидроксибенз",
        "фенилглиокс",
        "кофейн",
    ]):
        return "xenobiotics"

    # Азотистый обмен
    if "оротов" in n:
        return "nitrogen_cycle"

    # Глутатион / oxidative stress
    if "пироглутам" in n:
        return "glutathione"

    return "other"


def grouped_domains(markers: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for m in markers or []:
        if is_suspicious_reference(m):
            continue
        domain = marker_domain(str(m.get("name") or ""))
        out.setdefault(domain, []).append(m)
    return out


def build_domain_interpretations(markers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Возвращает группы в формате, совместимом с formatter:
    {
        group,
        markers,
        interpretation,
        domain_key,
        count
    }
    """
    groups = grouped_domains(markers)
    out: List[Dict[str, Any]] = []

    labels = {
        "energy": "Энергетический обмен",
        "beta_oxidation": "Жирные кислоты и β-окисление",
        "cofactors": "Кофакторные и витамин-зависимые маркеры",
        "xenobiotics": "Внешняя метаболическая нагрузка",
        "nitrogen_cycle": "Азотистый обмен",
        "glutathione": "Окислительный стресс / глутатионовый контекст",
        "other": "Прочие метаболические изменения",
    }

    priority = [
        "energy",
        "beta_oxidation",
        "cofactors",
        "xenobiotics",
        "glutathione",
        "nitrogen_cycle",
        "other",
    ]

    for key in priority:
        items = groups.get(key) or []
        if not items:
            continue

        marker_names = []
        seen = set()
        for x in items:
            name = str(x.get("name") or "").strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                marker_names.append(name)

        out.append(
            {
                "group": labels[key],
                "markers": marker_names[:8],
                "interpretation": build_group_interpretation(
                    group_name=labels[key],
                    marker_names=marker_names[:8],
                ),
                "domain_key": key,
                "count": len(marker_names),
            }
        )

    return out


def build_rule_based_hypotheses(markers: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Возвращает hypotheses в формате:
    {
        hypothesis,
        confidence,
        comment
    }
    """
    groups = grouped_domains(markers)
    out: List[Dict[str, str]] = []

    # Гипотеза + комментарий через organic_acids_commentary_templates.build_hypothesis_comment (без назначений).
    if len(groups.get("energy", [])) >= 1 or len(groups.get("beta_oxidation", [])) >= 2:
        h = "Нужна оценка энергетического и жирового обмена"
        out.append({"hypothesis": h, "confidence": "low", "comment": build_hypothesis_comment(hypothesis=h)})

    if len(groups.get("cofactors", [])) >= 2:
        h = "Возможен вклад кофакторной / витаминной недостаточности"
        out.append({"hypothesis": h, "confidence": "low", "comment": build_hypothesis_comment(hypothesis=h)})

    if len(groups.get("xenobiotics", [])) >= 2:
        h = "Возможен вклад внешней метаболической нагрузки"
        out.append({"hypothesis": h, "confidence": "low", "comment": build_hypothesis_comment(hypothesis=h)})

    if len(groups.get("glutathione", [])) >= 1:
        h = "Возможен окислительный стресс / напряжение глутатионового обмена"
        out.append({"hypothesis": h, "confidence": "low", "comment": build_hypothesis_comment(hypothesis=h)})

    if len(groups.get("nitrogen_cycle", [])) >= 1:
        h = "Нужна осторожная оценка азотистого обмена"
        out.append({"hypothesis": h, "confidence": "low", "comment": build_hypothesis_comment(hypothesis=h)})

    return out[:5]


def build_ranked_summary(markers: List[Dict[str, Any]]) -> List[str]:
    """
    Оставляю для совместимости со старым кодом.
    Новый formatter может не использовать, но другие места проекта не должны падать.
    """
    groups = build_domain_interpretations(markers)
    if not groups:
        return [
            "Выраженных надёжно интерпретируемых отклонений среди распознанных маркеров не выявлено.",
            "Профиль не является диагностическим сам по себе.",
        ]

    lines: List[str] = []
    main = groups[:3]

    if any(g["domain_key"] in ("energy", "beta_oxidation") for g in main):
        lines.append("Есть признаки сдвига энергетического обмена и/или обмена жирных кислот.")

    if any(g["domain_key"] == "cofactors" for g in main):
        lines.append("Есть отдельные неспецифичные маркеры возможного кофакторного или витаминного дисбаланса.")

    if any(g["domain_key"] == "xenobiotics" for g in main):
        lines.append("Есть маркеры, которые могут соответствовать внешней метаболической нагрузке.")

    if any(g["domain_key"] == "glutathione" for g in main):
        lines.append("Есть сигнал, который может быть связан с окислительным стрессом.")

    if any(g["domain_key"] == "nitrogen_cycle" for g in main):
        lines.append("Отдельные показатели требуют осторожной оценки азотистого обмена, но не позволяют делать сильные выводы.")

    lines.append("Профиль органических кислот не устанавливает диагноз изолированно и требует клинической корреляции.")
    return lines[:5]
