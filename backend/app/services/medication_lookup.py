from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from app.services.clinical_intent_semantics import combine_lexical_and_semantic_treatment_score


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_MED_ROOT = _PROJECT_ROOT / "medical_knowledge" / "medications"
_DRUGS_DIR = _MED_ROOT / "drugs"
_DRUG_INDEX_FILE = _MED_ROOT / "indexes" / "drug_lookup_index.json"
_COMPLAINT_LINKS_FILE = _MED_ROOT / "links" / "complaint_treatment_index.json"
_DISEASE_LINKS_FILE = _MED_ROOT / "links" / "disease_treatment_index.json"
_SHARED_RULES_FILE = _MED_ROOT / "shared" / "shared_rules.json"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-zа-яё0-9\-\+\/]+", _norm(text)) if t]


def _is_nonmedical_test_phrase(text: str) -> bool:
    q = _norm(text)
    if not q:
        return True
    checks = (
        "ты меня слышишь",
        "вы меня слышите",
        "меня слышно",
        "проверка микрофона",
        "проверка связи",
        "алло",
        "1 2 3",
        "раз два три",
    )
    return any(x in q for x in checks)


def _read_json_any(path: Path) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


@lru_cache(maxsize=1)
def _load_drug_cards() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not _DRUGS_DIR.exists():
        return out
    for fp in sorted(_DRUGS_DIR.glob("*.json")):
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        drug_id = str(payload.get("id") or fp.stem).strip()
        if not drug_id:
            continue
        out[drug_id] = payload
    return out


@lru_cache(maxsize=1)
def _drug_index() -> dict[str, list[str]]:
    payload = _read_json_any(_DRUG_INDEX_FILE)
    out: dict[str, list[str]] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            ids = [str(x).strip() for x in (value if isinstance(value, list) else [value]) if str(x).strip()]
            nk = _norm(str(key))
            if nk and ids:
                out[nk] = ids
        return out
    if isinstance(payload, list):
        for row in payload:
            if not isinstance(row, dict):
                continue
            drug_id = str(row.get("drug_id") or "").strip()
            if not drug_id:
                continue
            for name in row.get("names") or []:
                nk = _norm(str(name))
                if nk:
                    out[nk] = [drug_id]
    return out


def _entries_from_links(payload: Any, id_key: str) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    if isinstance(payload, dict):
        for display, row in payload.items():
            if isinstance(row, dict):
                out.append((str(display).strip(), row))
        return out
    if isinstance(payload, list):
        for row in payload:
            if not isinstance(row, dict):
                continue
            display = str(row.get("display_name") or row.get(id_key) or "").strip()
            if display:
                out.append((display, row))
    return out


@lru_cache(maxsize=1)
def _complaint_links() -> list[tuple[str, dict[str, Any]]]:
    return _entries_from_links(_read_json_any(_COMPLAINT_LINKS_FILE), "complaint_id")


@lru_cache(maxsize=1)
def _disease_links() -> list[tuple[str, dict[str, Any]]]:
    return _entries_from_links(_read_json_any(_DISEASE_LINKS_FILE), "disease_id")


@lru_cache(maxsize=1)
def _shared_rules() -> dict[str, Any]:
    payload = _read_json_any(_SHARED_RULES_FILE)
    return payload if isinstance(payload, dict) else {}


def _is_doctor_only(access: str) -> bool:
    low = _norm(access)
    return ("rx" in low) and ("otc_or_rx" not in low) and ("rx_or_otc" not in low)


def _is_otc(access: str) -> bool:
    low = _norm(access)
    return ("otc" in low) and (not _is_doctor_only(low))


def _card_name(card: dict[str, Any], fallback: str = "") -> str:
    return str(card.get("name") or card.get("generic_name") or card.get("id") or fallback).strip()


def _card_group(card: dict[str, Any]) -> str:
    raw = str(card.get("group") or card.get("subgroup") or card.get("category") or "Препаратная группа").strip()
    mapping = {
        "doac": "Прямой пероральный антикоагулянт",
        "systemic_steroid": "Системный глюкокортикостероид",
        "ssri": "Антидепрессант (СИОЗС)",
        "insulin": "Инсулин",
    }
    return mapping.get(raw.lower(), raw)


def _card_access(card: dict[str, Any], item: dict[str, Any] | None = None) -> str:
    src = item if isinstance(item, dict) else {}
    return str(
        src.get("access_level")
        or src.get("rx_status")
        or card.get("access_level")
        or card.get("rx_status")
        or ""
    ).strip()


def _card_uses(card: dict[str, Any]) -> list[str]:
    return [str(x).strip() for x in (card.get("usual_uses") or card.get("common_uses") or []) if str(x).strip()]


def _card_warnings(card: dict[str, Any]) -> list[str]:
    out = [str(x).strip() for x in (card.get("safe_use_notes") or card.get("key_warnings") or []) if str(x).strip()]
    extra = str(card.get("doctor_only_warning") or "").strip()
    if extra:
        out.append(extra)
    return out


def _is_antibiotic(drug_card: dict[str, Any], item: dict[str, Any]) -> bool:
    blob = " ".join(
        [
            str((drug_card or {}).get("group") or ""),
            str((drug_card or {}).get("category") or ""),
            str((drug_card or {}).get("subgroup") or ""),
            str((drug_card or {}).get("description_short") or ""),
            str((item or {}).get("name") or ""),
            str((item or {}).get("short") or ""),
        ]
    ).lower()
    return any(k in blob for k in ("антибиот", "penicillin", "macrolid", "цефалоспор", "beta-lact"))


def _is_restricted_auto_class(drug_card: dict[str, Any], item: dict[str, Any]) -> bool:
    blob = " ".join(
        [
            str((drug_card or {}).get("group") or ""),
            str((drug_card or {}).get("category") or ""),
            str((drug_card or {}).get("subgroup") or ""),
            str((drug_card or {}).get("description_short") or ""),
            str((item or {}).get("name") or ""),
            str((item or {}).get("short") or ""),
        ]
    ).lower()
    keys = (
        "антибиот",
        "horm",
        "стероид",
        "гормон",
        "anticoag",
        "антикоаг",
        "doac",
        "warfarin",
        "heparin",
        "инсулин",
        "insulin",
        "ssri",
        "антидепресс",
        "benzodiazep",
        "антипсихот",
    )
    return any(k in blob for k in keys)


def _expand_analog_names(card: dict[str, Any]) -> list[str]:
    cards = _load_drug_cards()
    out: list[str] = []
    for a in (card.get("analogs") or []):
        raw = str(a).strip()
        if not raw:
            continue
        ref = cards.get(raw) or {}
        out.append(_card_name(ref, raw))
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        k = _norm(x)
        if not k or k in seen:
            continue
        seen.add(k)
        uniq.append(x)
    return uniq


def _build_name_to_drug_map() -> dict[str, str]:
    cards = _load_drug_cards()
    by_name: dict[str, str] = {}
    for name, ids in _drug_index().items():
        for drug_id in ids:
            if name and drug_id:
                by_name[name] = drug_id
    for drug_id, card in cards.items():
        keys = [
            card.get("name"),
            card.get("generic_name"),
            card.get("id"),
            *(card.get("aliases") or []),
            *(card.get("brand_examples") or []),
            *(card.get("lookup_tags") or []),
        ]
        for key in keys:
            nk = _norm(str(key))
            if nk:
                by_name[nk] = drug_id
    return by_name


@lru_cache(maxsize=1)
def _name_to_drug_map() -> dict[str, str]:
    return _build_name_to_drug_map()


def _find_drug_match(query: str) -> tuple[str, dict[str, Any], str] | None:
    q = _norm(query)
    if not q:
        return None
    by_name = _name_to_drug_map()
    cards = _load_drug_cards()
    if q in by_name:
        drug_id = by_name[q]
        return drug_id, (cards.get(drug_id) or {}), q
    best: tuple[str, dict[str, Any], str] | None = None
    best_score = 0.0
    q_tokens = set(_tokenize(q))
    for name, drug_id in by_name.items():
        if len(name) < 4:
            continue
        score = 0.0
        if q in name or name in q:
            score += 2.0
        overlap = len(q_tokens & set(_tokenize(name)))
        if overlap:
            score += overlap / max(1, len(set(_tokenize(name))))
        if score > best_score:
            best_score = score
            best = (drug_id, cards.get(drug_id) or {}, name)
    return best if best and best_score >= 1.1 else None


def _render_medication_response(drug_id: str, card: dict[str, Any]) -> str:
    drug_name = _card_name(card, drug_id)
    group = _card_group(card)
    uses = _card_uses(card)
    warnings = _card_warnings(card)
    analogs = _expand_analog_names(card)
    access = _card_access(card)
    access_line = "возможен без рецепта в зависимости от формы/рынка"
    if _is_doctor_only(access):
        access_line = "отпуск только по рецепту врача"
    elif _is_otc(access):
        access_line = "обычно без рецепта (OTC)"
    if _is_antibiotic(card, {}):
        warnings = ["Антибиотики автоматически не назначаются."] + warnings
    if not warnings:
        warnings = ["Учитывайте противопоказания и совместимость с текущими препаратами."]
    if access_line not in warnings:
        warnings.append(access_line)
    return "\n".join(
        [
            f"Препарат: {drug_name}",
            f"Группа: {group}",
            "Обычно применяют при: " + ("; ".join(uses[:3]) if uses else "по профильным показаниям."),
            "Важно: " + "; ".join(warnings[:3]),
            "Аналоги: " + ("; ".join(analogs[:4]) if analogs else "подбираются врачом по показаниям."),
        ]
    )


def _entry_match_score(query: str, name: str, entry_id: str) -> float:
    q = _norm(query)
    nm = _norm(name)
    eid = _norm(entry_id)
    if not q or not (nm or eid):
        return 0.0
    score = 0.0
    if q == nm or q == eid:
        score += 5.0
    if q in nm or nm in q:
        score += 2.5
    stop = {
        "чем",
        "лечить",
        "что",
        "как",
        "при",
        "и",
        "или",
        "мне",
        "меня",
        "обычно",
        "помогает",
        "в",
        "на",
        "по",
        "из",
        "к",
        "у",
        "о",
        "об",
        "за",
        "от",
        "до",
        "без",
        "для",
        "про",
        "с",
        "со",
    }
    # Короткие токены (предлоги «с», «в» и т.п.) давали ложный overlap с названиями вроде «кашель с мокротой».
    q_tokens = {
        t
        for t in _tokenize(q)
        if t not in stop and not t.isdigit() and len(t) >= 3
    }
    n_tokens = {t for t in _tokenize(nm + " " + eid) if len(t) >= 3}
    if q_tokens and n_tokens:
        overlap = len(q_tokens & n_tokens)
        score += overlap * 0.9
        score += overlap / max(1, len(q_tokens))
    return score


def _phrase_ngram_bonus(query: str, display: str, entry_id: str) -> float:
    """Бонус за совпадение 2–3-словных фрагментов запроса с названием записи (смысл, не только одиночные токены)."""
    q = _norm(query)
    blob = _norm(str(display or "") + " " + str(entry_id or ""))
    if len(q) < 5 or len(blob) < 5:
        return 0.0
    toks = _tokenize(q)
    bonus = 0.0
    for n in (3, 2):
        for i in range(len(toks) - n + 1):
            phrase = " ".join(toks[i : i + n])
            if sum(1 for c in phrase if c.isalpha()) < 5:
                continue
            if phrase in blob:
                bonus += 1.15 * (n / 3.0)
    return min(bonus, 4.0)


def _resolve_option_items(values: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(values, list):
        return out
    cards = _load_drug_cards()
    for value in values:
        if isinstance(value, dict):
            row = dict(value)
            if not row.get("drug_id") and row.get("id"):
                row["drug_id"] = row.get("id")
            out.append(row)
            continue
        drug_id = str(value).strip()
        if not drug_id:
            continue
        card = cards.get(drug_id) or {}
        out.append(
            {
                "drug_id": drug_id,
                "name": _card_name(card, drug_id),
                "access_level": _card_access(card),
                "short": str(card.get("description_short") or "").strip(),
            }
        )
    return out


def _classify_treatment_options(options: list[dict[str, Any]]) -> tuple[list[str], list[str], list[str]]:
    cards = _load_drug_cards()
    otc: list[str] = []
    doctor: list[str] = []
    analogs: list[str] = []
    for item in options:
        if not isinstance(item, dict):
            continue
        drug_id = str(item.get("drug_id") or "").strip()
        card = cards.get(drug_id) or {}
        name = str(item.get("name") or _card_name(card, drug_id)).strip()
        if any(x in _norm(name + " " + drug_id) for x in ("placeholder", "todo", "tbd")):
            continue
        access = _card_access(card, item)
        restricted = _is_antibiotic(card, item) or _is_restricted_auto_class(card, item)
        if restricted or _is_doctor_only(access):
            if name:
                doctor.append(f"{name} (отпуск только по рецепту врача)")
        elif _is_otc(access):
            if name:
                otc.append(name)
        else:
            if name:
                doctor.append(f"{name} (отпуск только по рецепту врача)")
        for a in _expand_analog_names(card)[:3]:
            if a:
                analogs.append(a)
    def _uniq(values: list[str], limit: int) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = _norm(value)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(value)
            if len(out) >= limit:
                break
        return out
    return _uniq(otc, 6), _uniq(doctor, 6), _uniq(analogs, 7)


def _priority() -> list[str]:
    p = _shared_rules().get("priority")
    if isinstance(p, list) and p:
        out = [str(x).strip() for x in p if str(x).strip()]
        if out:
            return out
    return ["safe_general_support", "otc_options", "doctor_only_options"]


def _render_treatment_response(display_name: str, safe_support: list[str], otc: list[str], doctor: list[str], analogs: list[str], notes: str) -> str:
    when_doctor = str(notes or "").strip() or "Если нет улучшения 24-48 часов, появляются red flags или выраженное ухудшение."
    blocks = {
        "safe_general_support": "Что обычно помогает без лекарств: " + ("; ".join(safe_support[:4]) if safe_support else "покой, питье, щадящий режим и контроль триггеров."),
        "otc_options": "Какие лекарства могут использоваться: " + ("; ".join(otc[:4]) if otc else "симптоматические OTC-опции по инструкции."),
        "doctor_only_options": "Что только по рецепту врача: " + ("; ".join(doctor[:4]) if doctor else "при необходимости врач подбирает рецептурную терапию (отпуск только по рецепту врача)."),
    }
    lines = [f"Похоже на: {display_name}"]
    for key in _priority():
        if key in blocks:
            lines.append(blocks[key])
    lines.append("Аналоги: " + ("; ".join(analogs[:5]) if analogs else "подбираются по переносимости и показаниям."))
    lines.append("Когда к врачу: " + when_doctor)
    return "\n".join(lines)


def _find_treatment_entry(query: str, *, min_score: float = 0.8) -> tuple[str, dict[str, Any], str] | None:
    q = _norm(query)
    if not q:
        return None
    best: tuple[str, dict[str, Any], str] | None = None
    best_score = 0.0
    for display, row in _complaint_links():
        row_id = str(row.get("complaint_id") or display).strip()
        raw = _entry_match_score(q, display, row_id) + _phrase_ngram_bonus(q, display, row_id)
        score = combine_lexical_and_semantic_treatment_score(raw, query, display or row_id)
        if score > best_score:
            best_score = score
            best = ("complaint", row, display or row_id)
    for display, row in _disease_links():
        row_id = str(row.get("disease_id") or display).strip()
        raw = _entry_match_score(q, display, row_id) + _phrase_ngram_bonus(q, display, row_id)
        score = combine_lexical_and_semantic_treatment_score(raw, query, display or row_id)
        if score > best_score:
            best_score = score
            best = ("disease", row, display or row_id)
    return best if best and best_score >= float(min_score) else None


def _query_is_short_lookup(query: str) -> bool:
    tokens = _tokenize(query)
    if not tokens:
        return False
    if len(tokens) <= 7:
        return True
    q = _norm(query)
    return any(k in q for k in ("что за", "для чего", "аналоги", "чем леч", "что принять", "что помогает", "какие лекарства"))


def route_medication_lookup(
    user_message: str,
    *,
    complaint_protocol: Optional[dict[str, Any]] = None,
    mode_hint: Optional[str] = None,
) -> dict[str, Any] | None:
    q = _norm(user_message)
    if not q:
        return None
    if _is_nonmedical_test_phrase(q):
        return None
    hint = _norm(mode_hint or "")
    force_medication = hint in {"medication", "drug", "medicine", "лекарство", "препарат"}
    force_treatment = hint in {"treatment", "complaint", "disease", "жалоба", "болезнь"}
    drug_match = _find_drug_match(q)
    if drug_match and (_query_is_short_lookup(q) or force_medication):
        drug_id, card, matched = drug_match
        response = _render_medication_response(drug_id, card)
        return {
            "mode": "medication_lookup_mode",
            "response": response,
            "response_simple": response,
            "matched_label": _card_name(card, matched or drug_id),
        }
    if force_medication and not drug_match:
        return None

    treatment_min_score = 1.8 if force_treatment else 0.8
    treatment_hit = _find_treatment_entry(q, min_score=treatment_min_score)

    if treatment_hit and (_query_is_short_lookup(q) or force_treatment):
        hit_type, row, display = treatment_hit
        # Не подменять тему либидо/сексуального здоровья справочником про кашель/ОРВИ из-за общих слов в вопросе.
        dn = _norm(str(display or ""))
        if any(k in q for k in ("либид", "либдо", "сексуальн", "эректиль", "импотенц", "интим")) and any(
            k in dn for k in ("кашл", "мокрот", "горл", "насморк", "орви", "ангин", "фарингит", "бронхит", "пневмон")
        ):
            treatment_hit = None

    if treatment_hit and (_query_is_short_lookup(q) or force_treatment):
        hit_type, row, display = treatment_hit
        support = [str(x).strip() for x in (row.get("safe_general_support") or []) if str(x).strip()]
        notes = str(row.get("notes") or row.get("description") or row.get("analogs_hint") or "").strip()
        if hit_type == "complaint":
            options = _resolve_option_items(row.get("otc_options") or []) + _resolve_option_items(row.get("doctor_only_options") or [])
        else:
            if row.get("treatment_options") is not None:
                options = _resolve_option_items(row.get("treatment_options") or [])
            else:
                options = _resolve_option_items(row.get("otc_options") or []) + _resolve_option_items(row.get("doctor_only_options") or [])
        otc, doctor, analogs = _classify_treatment_options(options)
        response = _render_treatment_response(display, support, otc, doctor, analogs, notes)
        return {
            "mode": "treatment_lookup_mode",
            "response": response,
            "response_simple": response,
            "matched_label": display,
        }
    return None
