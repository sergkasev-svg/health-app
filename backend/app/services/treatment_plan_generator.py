"""
Генератор плана по маркерам органических кислот.
Вход: markers dict (pyroglutamic_acid_high, malonic_acid_high, sebacic_acid_high, figlu_high, hippuric_pattern).
Выход: core_actions, supplements, nutrition, tests, lifestyle + CTA для upsell.
"""
from __future__ import annotations

from typing import Any, Dict, List


def extract_markers_from_report(report: Dict[str, Any]) -> Dict[str, bool]:
    """
    Строит markers из physician report (organic acids).
    Использует: abnormal_markers_table (name, flag), clinical_scores.ranked_domains (key).
    """
    markers: Dict[str, bool] = {
        "pyroglutamic_acid_high": False,
        "malonic_acid_high": False,
        "sebacic_acid_high": False,
        "figlu_high": False,
        "hippuric_pattern": False,
    }

    def _norm(s: str) -> str:
        return (s or "").strip().lower().replace("ё", "е")

    # По доменам из clinical_scores
    ranked = report.get("clinical_scores") or {}
    domain_keys = [str(d.get("key") or "") for d in (ranked.get("ranked_domains") or [])[:6]]
    if "glutathione" in domain_keys:
        markers["pyroglutamic_acid_high"] = True
    if "energy" in domain_keys or "beta_oxidation" in domain_keys:
        markers["malonic_acid_high"] = True
        markers["sebacic_acid_high"] = True
    if "cofactors" in domain_keys:
        markers["figlu_high"] = True
    if "xenobiotics" in domain_keys:
        markers["hippuric_pattern"] = True

    # Уточнение по именам маркеров (abnormal или grouped)
    abnormal = report.get("abnormal_markers_table") or []
    groups = report.get("grouped_interpretation_table") or []
    all_names: List[str] = []
    for row in abnormal:
        name = _norm(str(row.get("name") or ""))
        if name:
            all_names.append(name)
    for g in groups:
        for m in g.get("markers") or []:
            all_names.append(_norm(str(m)))

    for n in all_names:
        if "пироглутам" in n:
            markers["pyroglutamic_acid_high"] = True
        if "малонов" in n:
            markers["malonic_acid_high"] = True
        if "себацин" in n:
            markers["sebacic_acid_high"] = True
        if "формиминоглутам" in n or "figlu" in n:
            markers["figlu_high"] = True
        if "метилгиппур" in n or "гиппур" in n or "миндальн" in n:
            markers["hippuric_pattern"] = True

    return markers


def extract_markers(lab_data: Dict[str, Any]) -> Dict[str, bool]:
    """
    Маппинг из сырых lab_data (ключи: pyroglutamic, malonic, sebacic, figlu, hippuric; значения: "high" и т.д.).
    Для совместимости с внешним API.
    """
    def _high(key: str) -> bool:
        return str((lab_data.get(key) or "")).strip().lower() == "high"

    return {
        "pyroglutamic_acid_high": _high("pyroglutamic"),
        "malonic_acid_high": _high("malonic"),
        "sebacic_acid_high": _high("sebacic"),
        "figlu_high": _high("figlu"),
        "hippuric_pattern": _high("hippuric"),
    }


def generate_plan(markers: Dict[str, bool]) -> Dict[str, List[str]]:
    """
    Генерирует структурированный план по маркерам.
    Возвращает: core_actions, supplements, nutrition, tests, lifestyle.
    Добавки и шаги — для обсуждения с врачом, не назначение.
    """
    plan: Dict[str, List[str]] = {
        "core_actions": [],
        "supplements": [],
        "nutrition": [],
        "tests": [],
        "lifestyle": [],
    }

    # Окислительный стресс
    if markers.get("pyroglutamic_acid_high"):
        plan["core_actions"].append("Снижение окислительного стресса")
        plan["supplements"].extend([
            "N-ацетилцистеин (NAC)",
            "Витамин C",
            "Глицин",
        ])

    # Энергия / митохондрии
    if markers.get("malonic_acid_high") or markers.get("sebacic_acid_high"):
        plan["core_actions"].append("Поддержка энергетического обмена")
        plan["supplements"].extend([
            "L-карнитин",
            "Коэнзим Q10",
            "Магний",
        ])
        plan["nutrition"].append("Регулярное питание без длительных голодовок")

    # Витамины
    if markers.get("figlu_high"):
        plan["core_actions"].append("Поддержка витаминных кофакторов")
        plan["supplements"].extend([
            "Фолат (B9)",
            "B12",
            "B6",
        ])
        plan["tests"].extend([
            "B12",
            "Фолиевая кислота",
            "Гомоцистеин",
        ])

    # Токсическая нагрузка
    if markers.get("hippuric_pattern"):
        plan["core_actions"].append("Снижение внешней нагрузки")
        plan["lifestyle"].extend([
            "Исключить бытовую химию с запахами",
            "Минимизировать пластик",
            "Убрать ультрапереработанные продукты",
        ])

    # Микробиом — всегда в план как база
    plan["nutrition"].extend([
        "Клетчатка (постепенно)",
        "Овощи ежедневно",
        "Ферментированные продукты",
    ])

    # Дедупликация списков с сохранением порядка
    for key in plan:
        seen: set = set()
        out: List[str] = []
        for x in plan[key]:
            x = str(x).strip()
            if not x or x in seen:
                continue
            seen.add(x)
            out.append(x)
        plan[key] = out

    return plan


def generate_cta(plan: Dict[str, List[str]]) -> str:
    """Текст CTA для upsell персонального плана восстановления."""
    if not (plan.get("core_actions") or plan.get("supplements") or plan.get("nutrition")):
        return ""

    return """
Хотите полный персональный план восстановления?

Мы составим для вас:
- питание
- добавки
- план восстановления энергии
- поддержку микробиома

👉 Получить персональный план
""".strip()
