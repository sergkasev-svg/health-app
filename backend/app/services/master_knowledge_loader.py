"""
Загрузка MASTER v3 — ядро медицинского AI-продукта (AUTO DIAGNOSIS ENGINE, 50+ бактерий, 100+ маркеров, 30+ сценариев).
Используется для RAG, расширения промптов и слоя интерпретации.
"""
from __future__ import annotations

from pathlib import Path

_KNOWLEDGE_ROOT = Path(__file__).resolve().parent.parent / "knowledge"
_MASTER_V3_PATH = _KNOWLEDGE_ROOT / "za_zdorovie_MASTER_v3.md"
_METHOD_DIGEST_PATH = _KNOWLEDGE_ROOT / "za_zdorovie_methodichka_digest.md"
_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"
_KNOWLEDGE_PROMPT_FILES = [
    "knowledge_master_prompt.txt",
    "knowledge_blood_prompt.txt",
    "knowledge_organic_acids_prompt.txt",
    "knowledge_fatty_acids_prompt.txt",
    "knowledge_microbiome_prompt.txt",
    "knowledge_super_prompt.txt",
    "knowledge_urine_prompt.txt",
    "knowledge_stool_prompt.txt",
    "knowledge_saliva_prompt.txt",
    "knowledge_skin_mucosa_prompt.txt",
]

# Ограничение длины для вставки в промпт (символы)
_MASTER_PROMPT_MAX_CHARS = 8000


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def load_master_v3_raw() -> str:
    """Возвращает полный текст MASTER v3 или пустую строку при ошибке."""
    return _read_text(_MASTER_V3_PATH)


def load_methodichka_digest_raw() -> str:
    """
    Возвращает клинический digest по внутренним методическим PDF:
    - Методичка1.pdf
    - Дополнительные слайды (1).pdf
    """
    return _read_text(_METHOD_DIGEST_PATH)


def load_knowledge_prompt_pack_raw() -> str:
    """
    Возвращает объединённый пакет knowledge-подсказок по группам анализов.
    Файлы лежат в backend/app/prompts.
    """
    chunks = []
    for name in _KNOWLEDGE_PROMPT_FILES:
        p = _PROMPTS_ROOT / name
        txt = _read_text(p)
        if not txt:
            continue
        chunks.append(f"[{name}]\n{txt}")
    return "\n\n".join(chunks).strip()


def get_master_knowledge_for_prompt(max_chars: int = _MASTER_PROMPT_MAX_CHARS) -> str:
    """
    Возвращает объединённый knowledge-слой:
    - MASTER v3
    - prompt pack по группам анализов
    - digest методичек (клинические акценты)
    обрезанный до max_chars для вставки в системный промпт или kb_hint.
    Если файла нет — пустая строка.
    """
    parts = []
    master = load_master_v3_raw()
    if master:
        parts.append("[MASTER v3]\n" + master)
    pack = load_knowledge_prompt_pack_raw()
    if pack:
        parts.append("[KNOWLEDGE PROMPT PACK]\n" + pack)
    digest = load_methodichka_digest_raw()
    if digest:
        parts.append("[METHODICHKA DIGEST]\n" + digest)
    raw = "\n\n".join(parts).strip()
    if not raw:
        return ""
    if max_chars <= 0 or len(raw) <= max_chars:
        return raw
    return raw[:max_chars] + "\n\n[... обрезано по лимиту символов ...]"
