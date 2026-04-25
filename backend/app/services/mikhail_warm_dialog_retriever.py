"""
Эталонные «тёплые» диалоги Михаила для few-shot в system prompt консультации.
Источники:
  - za_zdorovie_clinical_engine/engine/mikhail_warm_dialog_examples.json (база)
  - za_zdorovie_clinical_engine/engine/mikhail_warm_dialog_scenarios_49_216.json (доп. сценарии; иначе 49_143 / 49_128 / 49_93)
Подбор: пересечение тегов с текстом пользователя (простая эвристика).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _json_candidate_paths(filename: str) -> list[Path]:
    base = Path(__file__).resolve()
    # …/health-app/backend/app/services/this.py → health-app = parents[3]
    roots = [
        base.parents[3] / "za_zdorovie_clinical_engine" / "engine" / filename,
        base.parents[2] / "za_zdorovie_clinical_engine" / "engine" / filename,
        Path.cwd() / "za_zdorovie_clinical_engine" / "engine" / filename,
    ]
    seen: set[str] = set()
    out: list[Path] = []
    for p in roots:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _try_load_dialog_json(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file():
            return None
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict) and isinstance(data.get("dialogs"), list):
            return data
    except Exception:
        return None
    return None


def _load_examples_payload() -> dict[str, Any]:
    primary: dict[str, Any] | None = None
    for path in _json_candidate_paths("mikhail_warm_dialog_examples.json"):
        primary = _try_load_dialog_json(path)
        if primary is not None:
            break
    if primary is None:
        primary = {}

    dialogs: list[dict[str, Any]] = [
        d for d in (primary.get("dialogs") or []) if isinstance(d, dict)
    ]
    seen_ids: set[Any] = {d.get("id") for d in dialogs if d.get("id") is not None}

    for fname in (
        "mikhail_warm_dialog_scenarios_49_216.json",
        "mikhail_warm_dialog_scenarios_49_143.json",
        "mikhail_warm_dialog_scenarios_49_128.json",
        "mikhail_warm_dialog_scenarios_49_93.json",
    ):
        loaded = False
        for path in _json_candidate_paths(fname):
            extra = _try_load_dialog_json(path)
            if extra is None:
                continue
            for d in (extra.get("dialogs") or []):
                if not isinstance(d, dict):
                    continue
                did = d.get("id")
                if did is not None and did in seen_ids:
                    continue
                if did is not None:
                    seen_ids.add(did)
                dialogs.append(d)
            loaded = True
            break
        if loaded:
            break

    out = dict(primary)
    out["dialogs"] = dialogs
    return out


def _normalize_user_blob(text: str) -> str:
    s = (text or "").lower()
    s = re.sub(r"[^\w\s\u0400-\u04ff-]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _score_dialog(user_blob: str, dialog: dict[str, Any], *, raw_message: str = "") -> int:
    tags = dialog.get("tags") or []
    if not isinstance(tags, list):
        return 0
    score = 0
    raw_blob = _normalize_user_blob(raw_message) if raw_message else user_blob
    turns = dialog.get("turns") or []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        if str(turn.get("role") or "").strip().lower() != "user":
            continue
        ut = _normalize_user_blob(str(turn.get("text") or ""))
        if ut and len(ut) >= 16 and ut in raw_blob:
            score += 10
        break
    for t in tags:
        if not isinstance(t, str):
            continue
        tt = t.strip().lower()
        if len(tt) < 3:
            continue
        if tt in user_blob:
            score += 3
            continue
        parts = [p for p in re.split(r"[\s/]+", tt) if len(p) >= 4]
        for p in parts:
            if p in user_blob:
                score += 1
    # лёгкий бонус по id (например chest + грудь)
    did = str(dialog.get("id") or "").lower()
    if "chest" in did and ("груд" in user_blob or "груди" in user_blob):
        score += 2
    if "teen" in did and ("школ" in user_blob or "подрост" in user_blob or "учёб" in user_blob or "учеб" in user_blob):
        score += 2
    if "oncology" in did or "fear" in did:
        if any(x in user_blob for x in ("рак", "онколог", "лимфоцит", "анализ", "страшно", "боюсь")):
            score += 2
    if "weight" in did and ("вес" in user_blob or "похуд" in user_blob or "сброс" in user_blob):
        score += 2
    if "fatigue" in did and ("устал" in user_blob or "апати" in user_blob or "встать тяжело" in user_blob):
        score += 2
    return score


def select_warm_dialog_examples(user_message: str, *, max_dialogs: int = 2) -> list[dict[str, Any]]:
    payload = _load_examples_payload()
    dialogs = [d for d in (payload.get("dialogs") or []) if isinstance(d, dict)]
    if not dialogs:
        return []
    blob = _normalize_user_blob(user_message)
    ranked = sorted(
        ((_score_dialog(blob, d, raw_message=user_message), d) for d in dialogs),
        key=lambda x: (-x[0], str(x[1].get("id") or "")),
    )
    out: list[dict[str, Any]] = []
    for sc, d in ranked:
        if sc <= 0:
            break
        out.append(d)
        if len(out) >= max_dialogs:
            break
    return out


def format_warm_dialog_examples_block(
    user_message: str,
    *,
    max_dialogs: int = 2,
    max_chars: int = 7000,
) -> str:
    selected = select_warm_dialog_examples(user_message, max_dialogs=max_dialogs)
    if not selected:
        return ""
    lines: list[str] = [
        "[WARM_DIALOG_FEW_SHOT]",
        "Ниже 1–2 эталонных диалога в обновлённом стиле Михаила (по пересечению с вашей жалобой).",
        "Не копируй текст дословно. Сохраняй принципы: отзеркалить симптомы → короткая эмпатия → один вопрос за реплику → затем вывод и план (см. prompt_mihail.txt).",
        "Если пользователь ответил «да»/«хочу»/«расскажи» на твоё финальное предложение — сразу дай обещанный контент без новых уточняющих вопросов (раздел «ПОСЛЕ «ДА / ХОЧУ»» в prompt_mihail.txt).",
        "",
    ]
    for d in selected:
        did = str(d.get("id") or "").strip()
        tags = d.get("tags") or []
        tag_s = ",".join(str(t) for t in tags if str(t).strip()) if isinstance(tags, list) else ""
        lines.append(f"--- пример id={did} tags={tag_s} ---")
        for turn in d.get("turns") or []:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role") or "").strip().lower()
            text = str(turn.get("text") or "").strip()
            if not text:
                continue
            label = "Пользователь" if role == "user" else "Михаил"
            lines.append(f"{label}:\n{text}")
        lines.append("")
    out = "\n".join(lines).strip()
    if len(out) > max_chars:
        out = out[: max_chars - 20].rstrip() + "\n…[сокращено для лимита символов]"
    return out


def medication_handbook_policy_snippet() -> str:
    """Короткий блок для system prompt: справочники лекарств только как справка, не замена врачу."""
    return (
        "[MEDICATION_HANDBOOKS_POLICY]\n"
        "При вопросах о лекарствах опирайся на подключённые справочники (карточки препаратов, показания из индексов). "
        "Дай кратко: что это за группа/препарат, при каких жалобах обычно применяют, важные предостережения. "
        "Любые дозы и схемы — только «по инструкции к конкретному препарату и по назначению врача»; не подменяй врача и не поощряй самоназначение рецептурных средств."
    )
