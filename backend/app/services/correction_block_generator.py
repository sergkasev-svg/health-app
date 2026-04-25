"""
Автоматическое заполнение блока коррекции из анализа по правилам correction_rules.yaml.
Маппинг паттернов (маркеры high) → секции плана. Вставляешь — работает.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml
except ImportError:
    yaml = None

# Порядок правил задаёт приоритет секций в блоке
_RULES_ORDER = [
    "oxidative_stress",
    "energy_metabolism",
    "vitamin_cofactors",
    "external_load",
]

SECTION_LIBRARY = {
    "meal_timing": {
        "title": "Режим питания и интервалы",
        "text": [
            "Регулярное питание каждые 3–4 часа",
            "Избегать длительных пауз и пропуска приёмов пищи",
            "Оценить самочувствие между приёмами пищи (слабость, упадок энергии)",
        ],
    },
    "calories": {
        "title": "Калорийность",
        "text": [
            "Исключить дефицит калорий",
            "Избегать жёстких диет",
            "Оценить уровень энергии в течение дня",
        ],
    },
    "fats": {
        "title": "Жировой компонент",
        "text": [
            "Добавить качественные жиры (рыба, яйца, орехи)",
            "Убрать трансжиры и ультрапереработанные продукты",
            "Снизить избыток сахара",
        ],
    },
    "vitamins_check": {
        "title": "Проверка витаминов",
        "text": [
            "B12",
            "Фолиевая кислота (B9)",
            "Гомоцистеин",
        ],
    },
    "vitamins_correction": {
        "title": "Коррекция витаминов",
        "text": [
            "Обсуждается только после подтверждения дефицита",
            "Учитывать активные формы витаминов",
            "Не принимать витамины вслепую",
        ],
    },
    "external_analysis": {
        "title": "Анализ внешних факторов",
        "text": [
            "Лекарства и БАДы",
            "Бытовая химия",
            "Питание (добавки, красители)",
        ],
    },
    "detox_load_reduction": {
        "title": "Снижение нагрузки",
        "text": [
            "Минимизировать контакт с химией",
            "Сократить пластик (особенно горячее)",
            "Упростить рацион",
        ],
    },
    "antioxidants": {
        "title": "Антиоксидантная поддержка",
        "text": [
            "Поддержка антиоксидантной системы обсуждается с врачом",
            "Оценка глутатионового статуса",
            "Коррекция — только после подтверждения",
        ],
    },
}


def _load_correction_rules() -> Dict[str, Any]:
    base = Path(__file__).resolve().parent.parent
    path = base / "knowledge" / "labs" / "correction_rules.yaml"
    if not path.exists():
        return {"version": "1.0", "rules": {}}
    if not yaml:
        return {"version": "1.0", "rules": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {"version": "1.0", "rules": {}}
    except Exception:
        return {"version": "1.0", "rules": {}}


def _marker_is_high(markers: Dict[str, Any], key: str) -> bool:
    """Поддержка форматов: markers[key] == 'high' или markers[key_high] == True."""
    v = markers.get(key)
    if v is True:
        return True
    if isinstance(v, str) and str(v).strip().lower() == "high":
        return True
    alt = key.replace("_acid", "") + "_high"
    if alt in markers and markers[alt] is True:
        return True
    alt2 = key + "_high"
    if alt2 in markers and markers[alt2] is True:
        return True
    return False


def generate_correction_block(markers: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    По маркерам (pyroglutamic/high, malonic/high, sebacic/high, figlu/high, hippuric/high, mandelic/high
    или булевы *_high) возвращает список блоков { title, what_it_means, recommended } для отчёта.
    """
    # Нормализация: поддержка и "high", и bool
    normalized: Dict[str, Any] = {}
    for k in ("pyroglutamic", "malonic", "sebacic", "figlu", "hippuric", "mandelic"):
        normalized[k] = "high" if _marker_is_high(markers, k) else ""
    for k, v in markers.items():
        if k.endswith("_high") and v is True:
            base = k.replace("_acid_high", "").replace("_high", "")
            if base in ("pyroglutamic", "malonic", "sebacic", "figlu", "hippuric", "mandelic"):
                normalized[base] = "high"
        if k == "hippuric_pattern" and v:
            normalized["hippuric"] = "high"
            normalized["mandelic"] = "high"

    rules_config = _load_correction_rules()
    rules_map = rules_config.get("rules") or {}
    order = rules_config.get("rules_order") or _RULES_ORDER

    sections: List[str] = []
    for rule_id in order:
        rule = rules_map.get(rule_id)
        if not rule:
            continue
        triggered = False
        if "trigger" in rule:
            for mk, _ in (rule["trigger"] or {}).items():
                key = mk.replace("_acid", "")
                if normalized.get(key) == "high" or _marker_is_high(markers, key):
                    triggered = True
                    break
        if "trigger_any" in rule:
            for mk, _ in (rule["trigger_any"] or {}).items():
                key = mk.replace("_acid", "")
                if normalized.get(key) == "high" or _marker_is_high(markers, key):
                    triggered = True
                    break
        if triggered:
            for sec in rule.get("sections") or []:
                if sec not in sections:
                    sections.append(sec)

    if not sections and any(normalized.get(k) == "high" for k in ("pyroglutamic", "malonic", "sebacic", "figlu", "hippuric", "mandelic")):
        if normalized.get("pyroglutamic") == "high":
            sections.extend(["antioxidants", "detox_load_reduction"])
        if normalized.get("malonic") == "high" or normalized.get("sebacic") == "high":
            for s in ("meal_timing", "calories", "fats"):
                if s not in sections:
                    sections.append(s)
        if normalized.get("figlu") == "high":
            for s in ("vitamins_check", "vitamins_correction"):
                if s not in sections:
                    sections.append(s)
        if normalized.get("hippuric") == "high" or normalized.get("mandelic") == "high":
            for s in ("external_analysis", "detox_load_reduction"):
                if s not in sections:
                    sections.append(s)

    result: List[Dict[str, Any]] = []
    for sec_id in sections:
        lib = SECTION_LIBRARY.get(sec_id)
        if not lib:
            continue
        result.append({
            "title": lib.get("title") or sec_id,
            "what_it_means": "",
            "recommended": list(lib.get("text") or []),
        })
    return result


def markers_from_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Строит словарь маркеров для generate_correction_block из physician report.
    Ключи: pyroglutamic, malonic, sebacic, figlu, hippuric, mandelic; значения: "high" или "".
    """
    from app.services.treatment_plan_generator import extract_markers_from_report

    raw = extract_markers_from_report(report)
    return {
        "pyroglutamic": "high" if raw.get("pyroglutamic_acid_high") else "",
        "malonic": "high" if raw.get("malonic_acid_high") else "",
        "sebacic": "high" if raw.get("sebacic_acid_high") else "",
        "figlu": "high" if raw.get("figlu_high") else "",
        "hippuric": "high" if raw.get("hippuric_pattern") else "",
        "mandelic": "high" if raw.get("hippuric_pattern") else "",
    }
