"""
Авто-продажа внутри чата: показ CTA «Получить персональный план» после анализа/рекомендаций.
Дожим без агрессии: дать пользу → показать пробел → предложить следующий шаг.
Продаём решение, не «анализ» и не «витамины». Наружу — простой язык.
Логика и тексты офферов задаются ai_chat_upsell_scenario.json при наличии.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

_DEFAULT_TRIGGERS = [
    "has_pattern",
    "fatigue",
    "energy_issue",
    "vitamin_risk",
    "oxidative_stress",
    "external_load",
]


def _load_upsell_scenario() -> Dict[str, Any]:
    """Загружает ai_chat_upsell_scenario.json из app/knowledge. При ошибке — пустой dict."""
    try:
        path = Path(__file__).resolve().parent.parent / "knowledge" / "ai_chat_upsell_scenario.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _trigger_keys() -> List[str]:
    """Список ключей контекста, по которым решаем показывать upsell (из JSON или по умолчанию)."""
    scenario = _load_upsell_scenario()
    conditions = (scenario.get("sales_logic") or {}).get("trigger_conditions")
    if isinstance(conditions, list) and conditions:
        return [str(c) for c in conditions]
    return _DEFAULT_TRIGGERS


def detect_sales_moment(context: Dict[str, Any]) -> bool:
    """
    Показывать upsell когда есть хотя бы один триггер.
    Триггеры берутся из ai_chat_upsell_scenario.json (sales_logic.trigger_conditions) или по умолчанию.
    """
    keys = _trigger_keys()
    return any(bool(context.get(k)) for k in keys)


def should_show_upsell(user_data: Dict[str, Any]) -> bool:
    """Показывать upsell: использует detect_sales_moment + план/отчёт с находками."""
    if detect_sales_moment(user_data):
        return True
    if user_data.get("has_correction_plan"):
        return True
    if user_data.get("has_report_with_findings"):
        return True
    return False


def _soft_upsell_text() -> str:
    """Текст мягкого оффера: из JSON или встроенный по умолчанию."""
    scenario = _load_upsell_scenario()
    text = (scenario.get("sales_logic") or {}).get("soft_upsell")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return (
        "Я вижу здесь не один случайный показатель, а целый паттерн: "
        "нагрузка на обмен, признаки окислительного стресса, возможный вклад "
        "витаминно-кофакторных факторов и напряжение энергообмена.\n\n"
        "Могу собрать для вас полный персональный план:\n"
        "— что делать в первую очередь\n"
        "— что убрать, чтобы не мешать восстановлению\n"
        "— что проверить дальше\n"
        "— как выстроить питание и следующие шаги без лишней воды\n\n"
        "👉 Разблокировать полный персональный план"
    )


def build_soft_upsell(context: Dict[str, Any]) -> str:
    """
    Этап 1: после бесплатного разбора — мягкий дожим.
    Текст берётся из ai_chat_upsell_scenario.json (sales_logic.soft_upsell) или встроенный.
    """
    if not detect_sales_moment(context):
        return ""
    return _soft_upsell_text()


def _strong_upsell_text() -> str:
    """Текст сильного оффера: из JSON или встроенный по умолчанию."""
    scenario = _load_upsell_scenario()
    text = (scenario.get("sales_logic") or {}).get("strong_upsell")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return (
        "Вы уже получили базовую расшифровку, но главный вопрос обычно другой: "
        "что делать дальше и в каком порядке.\n\n"
        "В полном плане я соберу:\n"
        "✔ приоритет шагов на 7 дней\n"
        "✔ план на 2–4 недели\n"
        "✔ что может ухудшать состояние\n"
        "✔ какие проверки реально нужны, а какие можно не делать сейчас\n\n"
        "👉 Получить premium-план"
    )


def build_strong_upsell() -> str:
    """
    Этап 2: для горячего пользователя — сильный дожим.
    Текст из ai_chat_upsell_scenario.json (sales_logic.strong_upsell) или встроенный.
    """
    return _strong_upsell_text()


def generate_upsell(*, improved: bool = True) -> str:
    """
    Текст блока CTA для разблокировки полного плана.
    improved=True — версия с конверсией («Вы уже сделали первый шаг…»).
    """
    if improved:
        return """
Вы уже сделали первый шаг — разобрались с причинами.

Но сейчас у вас есть только общая картина.

Мы можем собрать для вас персональный план:

✔ что делать в первую очередь
✔ какие шаги дадут быстрый эффект
✔ как восстановить энергию
✔ как не усугубить состояние

👉 Получить персональный план
""".strip()
    return """
💡 Мы нашли факторы, которые могут влиять на ваше состояние.

Вы можете получить полный персональный план:

— что делать в первую очередь
— как восстановить энергию
— как снизить нагрузку на организм
— как поддержать микробиом

👉 Разблокировать полный план
""".strip()


def build_response(
    base_text: str,
    user_data: Dict[str, Any],
    *,
    improved_upsell: bool = True,
    use_strong_upsell: bool = False,
) -> str:
    """
    Добавляет upsell к ответу при detect_sales_moment.
    По умолчанию — мягкий дожим (build_soft_upsell). use_strong_upsell=True — сильный.
    Не продаём «анализ» или «витамины» — продаём решение.
    """
    if not base_text or not should_show_upsell(user_data):
        return base_text or ""
    if use_strong_upsell:
        upsell = build_strong_upsell()
    else:
        upsell = build_soft_upsell(user_data) or generate_upsell(improved=improved_upsell)
    return (base_text.strip() + "\n\n" + upsell).strip()


def build_chat_response(base_answer: str, context: Dict[str, Any], *, strong: bool = False) -> str:
    """
    Рабочая логика ответа: base_answer + upsell при detect_sales_moment.
    strong=True — сильный дожим (premium-план).
    """
    response = (base_answer or "").strip()
    if not detect_sales_moment(context):
        return response
    response += "\n\n" + (build_strong_upsell() if strong else build_soft_upsell(context))
    return response.strip()


def user_data_from_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Строит user_data для should_show_upsell / build_response из результата консультации.
    Использует report (treatment_plan, summary, clinical_scores), orchestrator_state.
    """
    report = result.get("report") or {}
    state = result.get("orchestrator_state") or {}
    summary_blob = " ".join(str(x).lower() for x in (report.get("summary") or []))
    plan = report.get("treatment_plan") or {}
    core_actions = plan.get("core_actions") or []
    has_plan = bool(core_actions or report.get("possible_correction_directions") or report.get("treatment_plan_cta"))

    fatigue = (
        "усталост" in summary_blob
        or "слабост" in summary_blob
        or "утомляем" in summary_blob
        or "нет сил" in summary_blob
        or any("энерг" in str(a).lower() or "усталост" in str(a).lower() for a in core_actions)
    )
    vitamin_risk = (
        "витамин" in summary_blob
        or "кофактор" in summary_blob
        or "b12" in summary_blob
        or "фолат" in summary_blob
        or "дефицит" in summary_blob
        or bool(plan.get("tests"))
    )
    energy_issue = (
        "энерг" in summary_blob
        or "митохондр" in summary_blob
        or "β-окислен" in summary_blob
        or any("энерг" in str(a).lower() for a in core_actions)
    )
    has_findings = bool(
        report.get("abnormal_markers_table")
        or report.get("top_hypotheses_table")
        or report.get("findings")
        or len(summary_blob) > 50
    )
    ranked = (report.get("clinical_scores") or {}).get("ranked_domains") or []
    oxidative_stress = (
        "окислительн" in summary_blob
        or "глутатион" in summary_blob
        or "антиоксидант" in summary_blob
    )
    external_load = (
        "внешн" in summary_blob
        or "нагрузк" in summary_blob
        or "ксенобиот" in summary_blob
        or "химия" in summary_blob
    )
    has_pattern = (
        len(ranked) >= 2
        or "паттерн" in summary_blob
        or (has_findings and (fatigue or vitamin_risk or energy_issue))
    )

    return {
        "fatigue": fatigue,
        "vitamin_risk": vitamin_risk,
        "energy_issue": energy_issue,
        "oxidative_stress": oxidative_stress,
        "external_load": external_load,
        "has_pattern": has_pattern,
        "has_correction_plan": has_plan,
        "has_report_with_findings": has_findings and (report.get("document_type") == "organic_acids_urine" or has_plan),
    }
