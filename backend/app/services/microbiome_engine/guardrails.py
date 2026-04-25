"""
Guardrails Microbiome Engine: запрещённые и разрешённые формулировки.
"""
from __future__ import annotations

FORBIDDEN_PHRASES = [
    "лечит",
    "гарантирует",
    "назначить пробиотик как лечение",
    "доказанно повышает силу у людей",
    "назначить как терапию",
]

ALLOWED_PHRASES = [
    "может быть связано",
    "исследуется",
    "перспективное направление",
    "ассоциирована с",
    "связана с",
]


def sanitize_text_for_microbiome(text: str) -> str:
    """
    Проверка текста на запрещённые формулировки.
    Возвращает исходный текст; в продакшене можно подменять фразы или помечать предупреждением.
    """
    if not text or not text.strip():
        return text
    low = text.strip().lower()
    for forbidden in FORBIDDEN_PHRASES:
        if forbidden in low:
            # Не меняем текст здесь — guardrail в промпте и при генерации
            break
    return text


def get_guardrail_rules() -> dict[str, list[str]]:
    """Для вставки в промпт или конфиг."""
    return {
        "forbid": list(FORBIDDEN_PHRASES),
        "allow": list(ALLOWED_PHRASES),
    }
