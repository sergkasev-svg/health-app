"""
Нормализация названий маркеров к каноническим кодам.
"""
from __future__ import annotations

import re
from typing import Dict, Optional

# Канонические коды и русские/английские варианты (нижний регистр для сравнения)
ALIASES: Dict[str, str] = {
    "холестерин общий": "total_cholesterol",
    "общий холестерин": "total_cholesterol",
    "total cholesterol": "total_cholesterol",
    "холестерин-лпнп": "ldl_cholesterol",
    "лпнп": "ldl_cholesterol",
    "ldl": "ldl_cholesterol",
    "холестерин лпнп": "ldl_cholesterol",
    "холестерин-лпвп": "hdl_cholesterol",
    "лпвп": "hdl_cholesterol",
    "hdl": "hdl_cholesterol",
    "холестерин лпвп": "hdl_cholesterol",
    "триглицериды": "triglycerides",
    "триглицерид": "triglycerides",
    "тг": "triglycerides",
    "гликозилированный гемоглобин (hba1c)": "hba1c",
    "гликированный гемоглобин": "hba1c",
    "hba1c": "hba1c",
    "гликированный": "hba1c",
    "фруктозамин": "fructosamine",
    "гомоцистеин": "homocysteine",
    "с-реактивный белок, высокочувствительный": "hs_crp",
    "высокочувствительный с-реактивный": "hs_crp",
    "hs-crp": "hs_crp",
    "hs crp": "hs_crp",
    "с-реактивный белок": "crp",
    "crp": "crp",
    "липопротеин (а)": "lp_a",
    "лп(а)": "lp_a",
    "lp(a)": "lp_a",
    "аполипопротеин а1": "apo_a1",
    "апо а1": "apo_a1",
    "apo a1": "apo_a1",
    "аполипопротеин в": "apo_b",
    "апо в": "apo_b",
    "apo b": "apo_b",
    "apob": "apo_b",
}


def _normalize_key(s: str) -> str:
    """Убираем лишние пробелы, дефисы, приводим к нижнему регистру для поиска."""
    if not s:
        return ""
    t = re.sub(r"[\s\-_]+", " ", str(s).lower().strip())
    return " ".join(t.split())


def normalize_marker_name(raw_name: str) -> Optional[str]:
    """
    Приводит сырое название маркера к каноническому коду.
    Возвращает None, если не найдено в ALIASES.
    """
    key = _normalize_key(raw_name)
    if not key:
        return None
    # Точное совпадение
    if key in ALIASES:
        return ALIASES[key]
    # Подстрока: ищем самый длинный совпадающий алиас
    for alias, code in sorted(ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in key or key in alias:
            return code
    return None
