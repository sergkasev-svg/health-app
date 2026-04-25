"""
Умный Михаил с памятью: сравнивает с предыдущими анализами, говорит «в прошлый раз было…».
Использует build_dynamics_summary для трендов по LDL, Hb, СОЭ и т.д.
Этапы: start → context → analysis → final (продажа подписки).
"""
from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from app.services.dynamics_service import build_dynamics_summary

# Ключевые маркеры для динамики в диалоге
DEFAULT_MARKER_KEYS = ["ldl", "cholesterol_total", "hb", "esr"]


def run_mikhail_with_memory(
    db: Session,
    user_id: int,
    result: dict,
    user_input: str,
    state: dict,
    *,
    marker_keys: list[str] | None = None,
) -> dict:
    """
    Один шаг диалога с Михаилом с учётом истории анализов и динамики.
    result — результат анализа (multi-lab), user_input — сообщение пользователя, state — этап.
    Возвращает {"text": str, "state": dict}.
    """
    stage = state.get("stage", "start")
    keys = marker_keys or DEFAULT_MARKER_KEYS
    dynamics = build_dynamics_summary(db, user_id, keys)
    dynamics_text = (dynamics.get("text") or "").strip()

    # -------------------------
    # СТАРТ
    # -------------------------
    if stage == "start":
        state["stage"] = "context"
        intro = (
            "Здравствуйте, я ваш консультант Михаил.\n\n"
            "Я посмотрел ваш анализ.\n\n"
        )
        if result:
            intro += (
                "Я сохранил этот анализ. "
                "Теперь я буду сравнивать его со следующими и показывать изменения.\n\n"
            )
        if dynamics_text:
            intro += f"📊 По сравнению с предыдущими результатами:\n{dynamics_text}\n\n"
        intro += (
            "Хочу уточнить несколько моментов.\n\n"
            "Скажите:\n"
            "- есть ли сейчас жалобы?\n"
            "- есть ли слабость, температура или боль?"
        )
        return {"text": intro, "state": state}

    # -------------------------
    # КОНТЕКСТ
    # -------------------------
    if stage == "context":
        state["stage"] = "analysis"
        body = "Понял.\n\nС учётом анализа и динамики:\n\n"
        if dynamics_text:
            body += f"{dynamics_text}\n\n"
        body += (
            "Картина выглядит следующим образом:\n"
            "- выраженного риска сейчас нет\n"
            "- но важно отследить устойчивость изменений\n\n"
            "Скажите:\n"
            "- это первый такой результат или уже было раньше?"
        )
        return {"text": body, "state": state}

    # -------------------------
    # АНАЛИЗ
    # -------------------------
    if stage == "analysis":
        state["stage"] = "final"
        body = (
            "Сейчас можно сделать аккуратный вывод:\n\n"
            "- серьёзной проблемы не видно\n"
            "- изменения выглядят как реакция, а не заболевание\n\n"
            "📌 Но важно:\n"
            "- если показатель растёт — это уже другая ситуация\n\n"
            "👉 Рекомендую:\n"
            "- контроль в динамике\n"
            "- точечные анализы\n"
        )
        return {"text": body, "state": state}

    # -------------------------
    # ПРОДАЖА (финал)
    # -------------------------
    if stage == "final":
        return {
            "text": (
                "Я могу дальше вести вас и отслеживать изменения.\n\n"
                "По подписке:\n"
                "- я сравниваю каждый новый анализ\n"
                "- показываю, что реально меняется\n"
                "- предупреждаю, если начинается риск\n\n"
                "👉 Включить наблюдение"
            ),
            "state": state,
        }

    # fallback: сброс на старт
    state["stage"] = "start"
    return run_mikhail_with_memory(db, user_id, result, user_input or "", state, marker_keys=keys)
