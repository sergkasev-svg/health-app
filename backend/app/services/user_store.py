"""
Хранение данных пользователя (профиль, настройки, документы, глобальный severity, виталы).
MVP: один пользователь на устройство, данные в JSON в data/users/{user_id}/.
"""
import json
import logging
import re
import time
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_DATA_ROOT = _BACKEND_DIR / "data" / "users"

DEFAULT_MODE = "BASIC"
DEFAULT_SUBSCRIPTION = "free"
VALID_MODES = ("BASIC", "COMFORT_45_PLUS")
VALID_SEVERITY = ("GREEN", "YELLOW", "RED")
CHAT_RETENTION_DAYS = 30
CHAT_WARN_DAY_1 = 27
CHAT_WARN_DAY_2 = 29


def _user_dir(user_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in user_id.strip())[:64] or "default"
    path = _DATA_ROOT / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("user_store_read_failed", extra={"path": str(path), "error": str(e)})
        return {}


def _write_json(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(path)
    except Exception as e:
        logger.warning("user_store_write_failed", extra={"path": str(path), "error": str(e)})
        raise


def get_or_create_user_id(user_id: Optional[str]) -> str:
    if not user_id or not str(user_id).strip():
        return "default"
    return str(user_id).strip()


def normalize_subject_id(subject_id: Optional[str]) -> str:
    raw = str(subject_id or "").strip().lower()
    if not raw:
        return "main"
    safe = "".join(c for c in raw if c.isalnum() or c in "-_")
    safe = safe[:40] if safe else "main"
    return safe or "main"


def get_settings(user_id: str) -> dict:
    path = _user_dir(user_id) / "settings.json"
    data = _read_json(path)
    mode = data.get("mode") or DEFAULT_MODE
    if mode not in VALID_MODES:
        mode = DEFAULT_MODE
    return {
        "mode": mode,
        "subscription": data.get("subscription") or DEFAULT_SUBSCRIPTION,
        "subscription_status": data.get("subscription_status") or "active",
        "subscription_expires_at": data.get("subscription_expires_at") or "",
        "billing_period": data.get("billing_period") or "",
        "free_features": data.get("free_features") or {},
        "dashboard_widgets": data.get("dashboard_widgets") or {},
        "dashboard_layout_mode": data.get("dashboard_layout_mode") or "manual",
        "sprint_focus": data.get("sprint_focus") or {},
        "non_medical_tone": data.get("non_medical_tone") or "friendly",
    }


def save_settings(user_id: str, payload: dict) -> dict:
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "settings.json"
    current = _read_json(path)
    for key in (
        "mode",
        "subscription",
        "subscription_status",
        "subscription_expires_at",
        "billing_period",
        "free_features",
        "dashboard_widgets",
        "dashboard_layout_mode",
        "sprint_focus",
        "non_medical_tone",
    ):
        if key in payload:
            current[key] = payload[key]
    _write_json(path, current)
    return get_settings(user_id)


def get_mikhail_conversation_prefs(user_id: str) -> dict:
    """Предпочтения стиля диалога Михаила (мягкий/более прямой и пр.)."""
    user_id = get_or_create_user_id(user_id)
    settings = get_settings(user_id)
    prefs = settings.get("mikhail_conversation_prefs")
    if not isinstance(prefs, dict):
        prefs = {}
    style = str(prefs.get("preferred_style") or "soft").strip().lower()
    if style not in {"soft", "direct"}:
        style = "soft"
    return {
        "preferred_style": style,
        "updated_at": str(prefs.get("updated_at") or ""),
        "signals": prefs.get("signals") if isinstance(prefs.get("signals"), dict) else {},
    }


def save_mikhail_conversation_prefs(user_id: str, payload: dict) -> dict:
    """Сохранить предпочтения стиля диалога Михаила в settings.json."""
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "settings.json"
    current = _read_json(path)
    prefs = current.get("mikhail_conversation_prefs")
    if not isinstance(prefs, dict):
        prefs = {}
    incoming = payload if isinstance(payload, dict) else {}
    style = str(incoming.get("preferred_style") or prefs.get("preferred_style") or "soft").strip().lower()
    if style not in {"soft", "direct"}:
        style = "soft"
    prefs["preferred_style"] = style
    signals = incoming.get("signals")
    if isinstance(signals, dict):
        prefs["signals"] = signals
    if "updated_at" in incoming:
        prefs["updated_at"] = str(incoming.get("updated_at") or "")
    current["mikhail_conversation_prefs"] = prefs
    _write_json(path, current)
    return get_mikhail_conversation_prefs(user_id)


def get_profile(user_id: str) -> dict:
    path = _user_dir(user_id) / "profile.json"
    data = _read_json(path)
    family_access = data.get("family_access")
    if not isinstance(family_access, list):
        family_access = []
    clean_family_access: list[dict[str, str]] = []
    for member in family_access[:5]:
        if not isinstance(member, dict):
            continue
        name = " ".join(str(member.get("name") or "").split())
        relation = " ".join(str(member.get("relation") or "").split())
        note = " ".join(str(member.get("note") or "").split())
        if not name and not relation and not note:
            continue
        clean_family_access.append({
            "name": name,
            "relation": relation,
            "note": note,
        })
    return {
        "name": data.get("name") or "",
        "address": data.get("address") or "",
        "chronic_conditions": data.get("chronic_conditions") or [],
        "allergies": data.get("allergies") or [],
        "family_history": data.get("family_history") or "",
        "family_access": clean_family_access,
        "privacy_consent": bool(data.get("privacy_consent")),
        "date_of_birth": data.get("date_of_birth") or "",
        "sex": data.get("sex") or "",
        "low_activity": bool(data.get("low_activity")) if data.get("low_activity") is not None else None,
    }


def save_profile(user_id: str, payload: dict) -> dict:
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "profile.json"
    current = _read_json(path)
    for key in ("name", "address", "chronic_conditions", "allergies", "family_history", "family_access", "privacy_consent", "date_of_birth", "sex", "low_activity"):
        if key in payload:
            if key == "privacy_consent":
                current[key] = bool(payload[key])
            elif key == "low_activity":
                current[key] = bool(payload[key]) if payload[key] is not None else None
            elif key == "name":
                current[key] = " ".join(str(payload[key] or "").split())
            elif key == "address":
                current[key] = " ".join(str(payload[key] or "").split())
            elif key == "family_access":
                members = payload.get("family_access")
                clean_members: list[dict[str, str]] = []
                if isinstance(members, list):
                    for member in members[:5]:
                        if not isinstance(member, dict):
                            continue
                        name = " ".join(str(member.get("name") or "").split())
                        relation = " ".join(str(member.get("relation") or "").split())
                        note = " ".join(str(member.get("note") or "").split())
                        if not name and not relation and not note:
                            continue
                        clean_members.append({
                            "name": name,
                            "relation": relation,
                            "note": note,
                        })
                current[key] = clean_members
            else:
                current[key] = payload[key]
    _write_json(path, current)
    return get_profile(user_id)


def append_emergency_audit_event(user_id: str, payload: dict) -> dict:
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "emergency_audit.json"
    current = _read_json(path)
    events = current.get("events")
    if not isinstance(events, list):
        events = []
    item = {
        "id": str(uuid.uuid4()),
        "created_at": int(time.time()),
        "source": str(payload.get("source") or "unknown")[:64],
        "channel": str(payload.get("channel") or "ui")[:64],
        "trigger_text": str(payload.get("trigger_text") or "")[:500],
        "status": str(payload.get("status") or "requested")[:32],
        "meta": payload.get("meta") if isinstance(payload.get("meta"), dict) else {},
    }
    events.append(item)
    current["events"] = events[-300:]
    _write_json(path, current)
    return item


def get_emergency_audit_events(user_id: str, limit: int = 200) -> list[dict]:
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "emergency_audit.json"
    data = _read_json(path)
    items = data.get("events")
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for it in items[-max(1, min(int(limit or 200), 1000)):]:
        if not isinstance(it, dict):
            continue
        row = dict(it)
        row["user_id"] = user_id
        out.append(row)
    out.sort(key=lambda x: float(x.get("created_at") or 0), reverse=True)
    return out


def get_emergency_analytics_snapshot(limit: int = 500, source: str = "") -> dict:
    lim = max(1, min(int(limit or 500), 2000))
    source_filter = str(source or "").strip().lower()
    source_aliases = {
        "footer": {"footer", "footer_button", "button_footer"},
        "chat": {"chat", "chat_button", "button_chat"},
        "voice": {"voice", "voice_command"},
    }
    accepted_sources: set[str] | None = None
    if source_filter and source_filter not in {"all", "*"}:
        accepted_sources = {source_filter}
        for _, aliases in source_aliases.items():
            if source_filter in aliases:
                accepted_sources = set(aliases)
                break
    all_events: list[dict] = []
    if _DATA_ROOT.exists():
        for user_dir in _DATA_ROOT.iterdir():
            if not user_dir.is_dir():
                continue
            user_id = user_dir.name
            for it in get_emergency_audit_events(user_id, limit=lim):
                src = str(it.get("source") or "").strip().lower()
                if accepted_sources is not None and src not in accepted_sources:
                    continue
                all_events.append(it)
    all_events.sort(key=lambda x: float(x.get("created_at") or 0), reverse=True)
    all_events = all_events[:lim]

    by_source: dict[str, int] = {}
    by_status: dict[str, int] = {}
    emotions: dict[str, int] = {}
    resistance_sum = 0.0
    resistance_count = 0
    interruptions_sum = 0
    runtime_linked = 0
    for ev in all_events:
        src = str(ev.get("source") or "unknown").strip() or "unknown"
        by_source[src] = by_source.get(src, 0) + 1
        st = str(ev.get("status") or "unknown").strip() or "unknown"
        by_status[st] = by_status.get(st, 0) + 1
        meta = ev.get("meta") if isinstance(ev.get("meta"), dict) else {}
        rt = meta.get("runtime_orchestrator_state") if isinstance(meta.get("runtime_orchestrator_state"), dict) else {}
        if rt:
            runtime_linked += 1
            emo = str(rt.get("emotion_state") or "unknown").strip() or "unknown"
            emotions[emo] = emotions.get(emo, 0) + 1
            try:
                resistance_sum += float(rt.get("resistance_level") or 0)
                resistance_count += 1
            except Exception:
                pass
            try:
                interruptions_sum += int(rt.get("interruption_count") or 0)
            except Exception:
                pass

    return {
        "total_events": len(all_events),
        "source_filter": source_filter or "all",
        "by_source": by_source,
        "by_status": by_status,
        "runtime_linked_events": runtime_linked,
        "runtime_link_ratio": (round(runtime_linked / len(all_events), 4) if all_events else 0),
        "emotion_breakdown": emotions,
        "avg_resistance_level": (round(resistance_sum / resistance_count, 2) if resistance_count else 0),
        "interruption_total": interruptions_sum,
        "events": all_events,
    }


def _coalesce_vital(device_val, manual_val):
    """Для плитки и API: значение с устройства важнее ручного."""
    return device_val if device_val is not None else manual_val


def get_vitals(user_id: str) -> dict:
    path = _user_dir(user_id) / "vitals.json"
    data = _read_json(path)
    manual_pulse = data.get("pulse")
    manual_temp = data.get("body_temp_c")
    manual_steps = data.get("steps")
    dev_pulse = data.get("pulse_device")
    dev_temp = data.get("body_temp_c_device")
    dev_steps = data.get("steps_device")
    return {
        "systolic": data.get("systolic"),
        "diastolic": data.get("diastolic"),
        "pulse": _coalesce_vital(dev_pulse, manual_pulse),
        "pulse_manual": manual_pulse,
        "body_temp_c": _coalesce_vital(dev_temp, manual_temp),
        "body_temp_c_manual": manual_temp,
        "steps": _coalesce_vital(dev_steps, manual_steps),
        "steps_manual": manual_steps,
        "weight_kg": data.get("weight_kg"),
        "height_cm": data.get("height_cm"),
        "hrv_rmssd": data.get("hrv_rmssd"),
        "sleep_hours": data.get("sleep_hours"),
        "sleep_quality": data.get("sleep_quality"),
        "updated_at": data.get("updated_at"),
    }


def save_vitals(user_id: str, payload: dict) -> dict:
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "vitals.json"
    current = _read_json(path)
    payload = dict(payload)
    src = str(payload.pop("source", "") or "").strip().lower()
    is_device = src == "device"

    if is_device:
        if "pulse" in payload and payload["pulse"] is not None:
            try:
                p = int(float(payload["pulse"]))
                if 40 <= p <= 200:
                    current["pulse_device"] = p
            except (TypeError, ValueError):
                pass
        if "body_temp_c" in payload and payload["body_temp_c"] is not None:
            try:
                t = float(payload["body_temp_c"])
                if 32.0 <= t <= 44.0:
                    current["body_temp_c_device"] = round(t, 1)
            except (TypeError, ValueError):
                pass
        if "steps" in payload and payload["steps"] is not None:
            try:
                s = int(float(payload["steps"]))
                if 0 <= s <= 200_000:
                    current["steps_device"] = s
            except (TypeError, ValueError):
                pass
    else:
        for key in ("systolic", "diastolic", "pulse", "height_cm"):
            if key in payload and payload[key] is not None:
                try:
                    current[key] = int(float(payload[key]))
                except (TypeError, ValueError):
                    pass
        if "weight_kg" in payload and payload["weight_kg"] is not None:
            try:
                current["weight_kg"] = round(float(payload["weight_kg"]), 1)
            except (TypeError, ValueError):
                pass
        for key in ("hrv_rmssd",):
            if key in payload and payload[key] is not None:
                try:
                    current[key] = int(float(payload[key]))
                except (TypeError, ValueError):
                    pass
        if "sleep_hours" in payload and payload["sleep_hours"] is not None:
            try:
                current["sleep_hours"] = round(float(payload["sleep_hours"]), 1)
            except (TypeError, ValueError):
                pass
        if "sleep_quality" in payload and payload["sleep_quality"]:
            current["sleep_quality"] = str(payload["sleep_quality"]).strip() or None
        if "body_temp_c" in payload and payload["body_temp_c"] is not None:
            try:
                t = float(payload["body_temp_c"])
                if 32.0 <= t <= 44.0:
                    current["body_temp_c"] = round(t, 1)
            except (TypeError, ValueError):
                pass
        if "steps" in payload and payload["steps"] is not None:
            try:
                s = int(float(payload["steps"]))
                if 0 <= s <= 200_000:
                    current["steps"] = s
            except (TypeError, ValueError):
                pass
    current["updated_at"] = round(time.time(), 2)
    _write_json(path, current)
    return get_vitals(user_id)


def get_documents(user_id: str, include_deleted: bool = False, subject_id: Optional[str] = None) -> list:
    path = _user_dir(user_id) / "documents.json"
    data = _read_json(path)
    items = data.get("items") or []
    sid = normalize_subject_id(subject_id) if subject_id is not None else None
    if sid is not None:
        items = [i for i in items if normalize_subject_id((i or {}).get("subject_id")) == sid]
    if include_deleted:
        return items
    return [i for i in items if not i.get("deleted_at")]


def add_document(user_id: str, doc: dict) -> list:
    """Добавить документ (анализ): id, type, summary, created_at, filename и т.д."""
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "documents.json"
    data = _read_json(path)
    items = data.get("items") or []
    doc_id = doc.get("id") or str(uuid.uuid4())
    item = {
        "id": doc_id,
        "type": doc.get("type") or "report",
        "summary": doc.get("summary") or "",
        "created_at": doc.get("created_at", time.time()),
        "filename": doc.get("filename") or "",
        "subject_id": normalize_subject_id(doc.get("subject_id")),
    }
    for key in ("severity", "extracted_text"):
        if key in doc:
            item[key] = doc[key]
    if "case_id" in doc:
        item["case_id"] = doc.get("case_id")
    items.append(item)
    data["items"] = items[-100:]  # храним последние 100
    _write_json(path, data)
    return data["items"]


def get_document_by_id(user_id: str, document_id: str, subject_id: Optional[str] = None) -> dict | None:
    """Вернуть документ по id или None."""
    items = get_documents(user_id, subject_id=subject_id)
    for it in items:
        if it.get("id") == document_id:
            return it
    return None


def update_document(user_id: str, document_id: str, updates: dict) -> dict | None:
    """Обновить поля документа (summary, extracted_text и т.д.). Возвращает обновлённый документ или None."""
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "documents.json"
    data = _read_json(path)
    items = list(data.get("items") or [])
    for i, it in enumerate(items):
        if it.get("id") == document_id:
            allowed = {k: v for k, v in updates.items() if k in ("summary", "filename", "extracted_text", "type", "case_id", "subject_id")}
            if "subject_id" in allowed:
                allowed["subject_id"] = normalize_subject_id(allowed.get("subject_id"))
            if allowed:
                items[i] = {**it, **allowed}
            data["items"] = items
            _write_json(path, data)
            return items[i]
    return None


def delete_document(user_id: str, document_id: str, subject_id: Optional[str] = None) -> dict | None:
    """Мягкое удаление: помечаем deleted_at. Файл не удаляется — можно вернуть."""
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "documents.json"
    data = _read_json(path)
    items = list(data.get("items") or [])
    sid = normalize_subject_id(subject_id) if subject_id is not None else None
    for i, it in enumerate(items):
        if it.get("id") == document_id:
            if sid is not None and normalize_subject_id((it or {}).get("subject_id")) != sid:
                continue
            items[i] = {**it, "deleted_at": time.time()}
            data["items"] = items
            _write_json(path, data)
            return items[i]
    return None


def restore_document(user_id: str, document_id: str, subject_id: Optional[str] = None) -> dict | None:
    """Вернуть документ из корзины (снять deleted_at)."""
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "documents.json"
    data = _read_json(path)
    items = list(data.get("items") or [])
    sid = normalize_subject_id(subject_id) if subject_id is not None else None
    for i, it in enumerate(items):
        if it.get("id") == document_id:
            if sid is not None and normalize_subject_id((it or {}).get("subject_id")) != sid:
                continue
            next_it = {k: v for k, v in it.items() if k != "deleted_at"}
            items[i] = next_it
            data["items"] = items
            _write_json(path, data)
            return next_it
    return None


def permanent_delete_document(user_id: str, document_id: str, subject_id: Optional[str] = None) -> dict | None:
    """Окончательно удалить документ из списка (для корзины). Возвращает удалённый документ для удаления файла с диска."""
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "documents.json"
    data = _read_json(path)
    items = list(data.get("items") or [])
    sid = normalize_subject_id(subject_id) if subject_id is not None else None
    for i, it in enumerate(items):
        if it.get("id") == document_id:
            if sid is not None and normalize_subject_id((it or {}).get("subject_id")) != sid:
                continue
            removed = items.pop(i)
            data["items"] = items
            _write_json(path, data)
            return removed
    return None


def clear_all_documents(user_id: str, subject_id: Optional[str] = None) -> int:
    """Очистить все загруженные документы (окончательно). Возвращает количество удалённых."""
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "documents.json"
    data = _read_json(path)
    items = list(data.get("items") or [])
    sid = normalize_subject_id(subject_id) if subject_id is not None else None
    keep = [x for x in items if (sid is not None and normalize_subject_id((x or {}).get("subject_id")) != sid)]
    if sid is None:
        keep = []
    count = len(items) - len(keep)
    if count > 0:
        data["items"] = keep
        _write_json(path, data)
    return count


def archive_voice_dialog(user_id: str, subject_id: Optional[str] = None) -> dict | None:
    """Перенести текущий чат в архив диалогов голосового консьержа. Очищает чат. Возвращает архивную запись или None."""
    user_id = get_or_create_user_id(user_id)
    sid = normalize_subject_id(subject_id)
    messages = get_chat_history(user_id, subject_id=sid)
    if not messages:
        return None
    path = _user_dir(user_id) / ("voice_dialog_archive_" + sid + ".json")
    data = _read_json(path)
    dialogs = list(data.get("dialogs") or [])
    preview = ""
    for m in messages:
        if (m or {}).get("role") == "user" and (m or {}).get("content"):
            preview = ((m or {}).get("content") or "")[:120].strip()
            break
    entry = {
        "id": str(uuid.uuid4()),
        "created_at": time.time(),
        "messages": messages,
        "preview": preview or "Диалог с консьержем",
    }
    dialogs.append(entry)
    data["dialogs"] = dialogs[-50:]
    _write_json(path, data)
    clear_chat_history(user_id, subject_id=sid)
    return entry


def get_archived_voice_dialogs(user_id: str, subject_id: Optional[str] = None) -> list:
    """Список архивных диалогов для истории (симптомы)."""
    sid = normalize_subject_id(subject_id)
    path = _user_dir(user_id) / ("voice_dialog_archive_" + sid + ".json")
    data = _read_json(path)
    dialogs = list(data.get("dialogs") or [])
    return sorted(dialogs, key=lambda d: float(d.get("created_at") or 0), reverse=True)


def restore_voice_dialog(user_id: str, dialog_id: str, subject_id: Optional[str] = None) -> dict | None:
    """Восстановить чат из архивного диалога. Возвращает запись диалога с messages или None."""
    user_id = get_or_create_user_id(user_id)
    sid = normalize_subject_id(subject_id)
    path = _user_dir(user_id) / ("voice_dialog_archive_" + sid + ".json")
    data = _read_json(path)
    dialogs = list(data.get("dialogs") or [])
    for d in dialogs:
        if d.get("id") == dialog_id:
            messages = d.get("messages") or []
            set_chat_history(user_id, messages, subject_id=sid)
            return {"id": d.get("id"), "created_at": d.get("created_at"), "messages": messages, "preview": d.get("preview")}
    return None


def delete_archived_voice_dialog(user_id: str, dialog_id: str, subject_id: Optional[str] = None) -> bool:
    """Удалить один архивный диалог голосового консьержа."""
    user_id = get_or_create_user_id(user_id)
    sid = normalize_subject_id(subject_id)
    path = _user_dir(user_id) / ("voice_dialog_archive_" + sid + ".json")
    data = _read_json(path)
    dialogs = list(data.get("dialogs") or [])
    next_dialogs = [d for d in dialogs if (d.get("id") or "") != dialog_id]
    if len(next_dialogs) == len(dialogs):
        return False
    data["dialogs"] = next_dialogs
    _write_json(path, data)
    return True


def clear_archived_voice_dialogs(user_id: str, subject_id: Optional[str] = None) -> int:
    """Очистить весь архив диалогов голосового консьержа."""
    user_id = get_or_create_user_id(user_id)
    sid = normalize_subject_id(subject_id)
    path = _user_dir(user_id) / ("voice_dialog_archive_" + sid + ".json")
    data = _read_json(path)
    dialogs = list(data.get("dialogs") or [])
    count = len(dialogs)
    if count > 0:
        data["dialogs"] = []
        _write_json(path, data)
    return count


def get_severity(user_id: str) -> dict:
    path = _user_dir(user_id) / "severity.json"
    data = _read_json(path)
    return {"severity": data.get("severity") or "GREEN", "source": data.get("source") or "dashboard"}


def save_severity(user_id: str, severity: str, source: str = "dashboard") -> dict:
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "severity.json"
    if severity not in VALID_SEVERITY:
        severity = "GREEN"
    _write_json(path, {"severity": severity, "source": source})
    return get_severity(user_id)


def get_chat_history(user_id: str, subject_id: Optional[str] = None) -> list:
    sid = normalize_subject_id(subject_id)
    path = _user_dir(user_id) / ("chat_" + sid + ".json")
    data = _read_json(path)
    return data.get("messages") or []


def append_chat_message(user_id: str, role: str, content: str, subject_id: Optional[str] = None) -> None:
    user_id = get_or_create_user_id(user_id)
    sid = normalize_subject_id(subject_id)
    path = _user_dir(user_id) / ("chat_" + sid + ".json")
    data = _read_json(path)
    messages = data.get("messages") or []
    messages.append({"role": role, "content": content})
    data["messages"] = messages[-100:]
    _write_json(path, data)


def clear_chat_history(user_id: str, subject_id: Optional[str] = None) -> None:
    user_id = get_or_create_user_id(user_id)
    sid = normalize_subject_id(subject_id)
    path = _user_dir(user_id) / ("chat_" + sid + ".json")
    _write_json(path, {"messages": []})


def _consultation_state_path(user_id: str, subject_id: Optional[str] = None) -> Path:
    """Файл состояния консультации на профиль (subject), в духе chat_{sid}.json."""
    sid = normalize_subject_id(subject_id)
    return _user_dir(user_id) / ("consultation_state_" + sid + ".json")


def get_consultation_state(user_id: str, subject_id: Optional[str] = None) -> dict:
    user_id = get_or_create_user_id(user_id)
    path = _consultation_state_path(user_id, subject_id)
    data = _read_json(path)
    if not isinstance(data, dict):
        data = {}
    sid = normalize_subject_id(subject_id)
    # Одноразовая миграция с глобального consultation_state.json только для профиля main
    if not data and sid == "main":
        legacy = _user_dir(user_id) / "consultation_state.json"
        if legacy.exists():
            old = _read_json(legacy)
            if isinstance(old, dict) and old:
                data = dict(old)
                _write_json(path, data)
    return data


def save_consultation_state(user_id: str, payload: dict, subject_id: Optional[str] = None) -> dict:
    user_id = get_or_create_user_id(user_id)
    path = _consultation_state_path(user_id, subject_id)
    current = _read_json(path)
    if not isinstance(current, dict):
        current = {}
    current.update(payload or {})
    current["updated_at"] = round(time.time(), 2)
    _write_json(path, current)
    return current


def clear_consultation_state(user_id: str, subject_id: Optional[str] = None) -> None:
    user_id = get_or_create_user_id(user_id)
    path = _consultation_state_path(user_id, subject_id)
    _write_json(path, {})


def get_user_state(user_id: str) -> dict:
    """Generic state bucket used by orchestrator-level branch memory."""
    return get_consultation_state(user_id, subject_id=None)


def save_user_state(user_id: str, payload: dict) -> dict:
    """Persist generic state bucket used by orchestrator-level branch memory."""
    return save_consultation_state(user_id, payload, subject_id=None)


def get_branch_memory(user_id: str, branch_name: str):
    user_state = get_user_state(user_id) or {}
    branch_memory = user_state.get("branch_memory", {})
    if not isinstance(branch_memory, dict):
        return None
    return branch_memory.get(branch_name)


def set_branch_memory(user_id: str, branch_name: str, memory_obj):
    def _json_safe(value):
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, dict):
            return {str(k): _json_safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_json_safe(v) for v in value]
        if isinstance(value, tuple):
            return [_json_safe(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if hasattr(value, "__dict__"):
            try:
                return _json_safe(dict(value.__dict__))
            except Exception:
                pass
        return str(value)

    user_state = get_user_state(user_id) or {}
    branch_memory = user_state.setdefault("branch_memory", {})
    if not isinstance(branch_memory, dict):
        branch_memory = {}
        user_state["branch_memory"] = branch_memory
    branch_memory[branch_name] = _json_safe(memory_obj)
    save_user_state(user_id, user_state)


def set_chat_history(user_id: str, messages: list[dict[str, str]], subject_id: Optional[str] = None) -> None:
    user_id = get_or_create_user_id(user_id)
    sid = normalize_subject_id(subject_id)
    path = _user_dir(user_id) / ("chat_" + sid + ".json")
    clean: list[dict[str, str]] = []
    for m in messages or []:
        role = str((m or {}).get("role") or "").strip().lower()
        content = str((m or {}).get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        clean.append({"role": role, "content": content})
    _write_json(path, {"messages": clean[-100:]})


def add_symptom_entry(user_id: str, text: str, source: str = "form", subject_id: Optional[str] = None) -> list:
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "symptoms.json"
    data = _read_json(path)
    entries = data.get("entries") or []
    entries.append({"text": text, "source": source, "created_at": time.time(), "subject_id": normalize_subject_id(subject_id)})
    data["entries"] = entries[-200:]
    _write_json(path, data)
    sid = normalize_subject_id(subject_id)
    return [e for e in data["entries"] if normalize_subject_id((e or {}).get("subject_id")) == sid]


def get_symptom_entries(user_id: str, subject_id: Optional[str] = None) -> list:
    path = _user_dir(user_id) / "symptoms.json"
    data = _read_json(path)
    sid = normalize_subject_id(subject_id) if subject_id is not None else None
    entries = list(data.get("entries") or [])
    if sid is None:
        return entries
    return [e for e in entries if normalize_subject_id((e or {}).get("subject_id")) == sid]


def delete_symptom_entries(user_id: str, indices: list[int], subject_id: Optional[str] = None) -> list:
    """Удалить записи симптомов по индексам (0-based). Возвращает обновлённый список entries."""
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "symptoms.json"
    data = _read_json(path)
    entries = list(data.get("entries") or [])
    sid = normalize_subject_id(subject_id)
    subject_entries = [e for e in entries if normalize_subject_id((e or {}).get("subject_id")) == sid]
    to_remove = {int(i) for i in indices if 0 <= int(i) < len(subject_entries)}
    kept_subject = [e for i, e in enumerate(subject_entries) if i not in to_remove]
    others = [e for e in entries if normalize_subject_id((e or {}).get("subject_id")) != sid]
    new_entries = others + kept_subject
    data["entries"] = new_entries
    _write_json(path, data)
    return kept_subject


def clear_symptom_entries(user_id: str, subject_id: Optional[str] = None) -> list:
    """Очистить всю историю симптомов. Возвращает пустой список."""
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "symptoms.json"
    data = _read_json(path)
    entries = list(data.get("entries") or [])
    sid = normalize_subject_id(subject_id)
    keep = [e for e in entries if normalize_subject_id((e or {}).get("subject_id")) != sid]
    _write_json(path, {"entries": keep})
    return []


def save_consultation_report(user_id: str, report: dict, subject_id: Optional[str] = None) -> str:
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "consultation_reports.json"
    data = _read_json(path)
    reports = data.get("reports") or []
    report_id = str(uuid.uuid4())
    reports.append({"id": report_id, "created_at": time.time(), "report": report, "subject_id": normalize_subject_id(subject_id)})
    data["reports"] = reports
    _write_json(path, data)
    return report_id


def attach_action_sequence_to_report(user_id: str, report_id: str, action_sequence: dict) -> bool:
    """Attach action_sequence payload to an existing consultation report by id."""
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "consultation_reports.json"
    data = _read_json(path)
    reports = list(data.get("reports") or [])
    for i, row in enumerate(reports):
        if row.get("id") == report_id:
            rep = dict(row.get("report") or {})
            rep["action_sequence"] = action_sequence or {}
            reports[i] = {**row, "report": rep}
            data["reports"] = reports
            _write_json(path, data)
            return True
    return False


def save_action_sequence(
    user_id: str,
    action_sequence: dict,
    *,
    source_message: str = "",
    report_id: Optional[str] = None,
    conclusion: bool = False,
) -> str:
    """
    Store action_sequence in a dedicated history file and optionally attach it to report.
    """
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "action_sequence_history.json"
    data = _read_json(path)
    items = list(data.get("items") or [])
    item_id = str(uuid.uuid4())
    item = {
        "id": item_id,
        "created_at": round(time.time(), 2),
        "source_message": (source_message or "")[:500],
        "report_id": report_id,
        "conclusion": bool(conclusion),
        "action_sequence": action_sequence or {},
    }
    items.append(item)
    data["items"] = items[-200:]
    _write_json(path, data)
    if report_id:
        attach_action_sequence_to_report(user_id, report_id, action_sequence or {})
    return item_id


def get_latest_action_sequence(user_id: str) -> dict:
    """Return latest action_sequence history item or empty dict."""
    path = _user_dir(user_id) / "action_sequence_history.json"
    data = _read_json(path)
    items = list(data.get("items") or [])
    return items[-1] if items else {}


def get_lab_cases(user_id: str, subject_id: Optional[str] = None) -> list:
    path = _user_dir(user_id) / "lab_cases.json"
    data = _read_json(path)
    sid = normalize_subject_id(subject_id) if subject_id is not None else None
    items = list(data.get("items") or [])
    if sid is None:
        return items
    return [x for x in items if normalize_subject_id((x or {}).get("subject_id")) == sid]


def _auto_case_name(user_id: str, subject_id: Optional[str] = None) -> str:
    """
    Build case folder name from first complaint (symptoms/chat) + date.
    """
    complaint = ""
    symptoms = get_symptom_entries(user_id, subject_id=subject_id)
    if symptoms:
        complaint = str((symptoms[0] or {}).get("text") or "").strip()
    if not complaint:
        chat = get_chat_history(user_id, subject_id=subject_id)
        for m in chat:
            if (m.get("role") or "").strip().lower() == "user":
                complaint = str(m.get("content") or "").strip()
                if complaint:
                    break
    if not complaint:
        return "Кейс " + time.strftime("%d.%m.%Y")
    complaint = re.sub(r"\s+", " ", complaint).strip()[:48]
    return complaint + " — " + time.strftime("%d.%m.%Y")


def create_lab_case(user_id: str, name: str, subject_id: Optional[str] = None) -> dict:
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "lab_cases.json"
    data = _read_json(path)
    items = list(data.get("items") or [])
    case = {
        "id": str(uuid.uuid4()),
        "name": (name or "").strip() or _auto_case_name(user_id, subject_id=subject_id),
        "subject_id": normalize_subject_id(subject_id),
        "created_at": round(time.time(), 2),
        "updated_at": round(time.time(), 2),
    }
    items.append(case)
    data["items"] = items[-200:]
    _write_json(path, data)
    return case


def get_or_create_named_lab_case(user_id: str, name: str, subject_id: Optional[str] = None) -> dict:
    user_id = get_or_create_user_id(user_id)
    target = (name or "").strip()
    for it in get_lab_cases(user_id, subject_id=subject_id):
        if (it.get("name") or "").strip() == target and target:
            return it
    return create_lab_case(user_id, target, subject_id=subject_id)


def update_lab_case(user_id: str, case_id: str, updates: dict, subject_id: Optional[str] = None) -> dict | None:
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "lab_cases.json"
    data = _read_json(path)
    items = list(data.get("items") or [])
    for i, it in enumerate(items):
        if it.get("id") == case_id and normalize_subject_id((it or {}).get("subject_id")) == normalize_subject_id(subject_id):
            next_item = dict(it)
            if "name" in updates:
                next_item["name"] = (updates.get("name") or "").strip() or it.get("name") or "Папка"
            next_item["updated_at"] = round(time.time(), 2)
            items[i] = next_item
            data["items"] = items
            _write_json(path, data)
            return next_item
    return None


def delete_lab_case(user_id: str, case_id: str, subject_id: Optional[str] = None) -> bool:
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "lab_cases.json"
    data = _read_json(path)
    items = list(data.get("items") or [])
    out = []
    removed = False
    for it in items:
        if it.get("id") == case_id and normalize_subject_id((it or {}).get("subject_id")) == normalize_subject_id(subject_id):
            removed = True
            continue
        out.append(it)
    if not removed:
        return False
    data["items"] = out
    _write_json(path, data)

    # Unlink documents from deleted case.
    docs_path = _user_dir(user_id) / "documents.json"
    docs_data = _read_json(docs_path)
    docs_items = list(docs_data.get("items") or [])
    touched = False
    for i, d in enumerate(docs_items):
        if d.get("case_id") == case_id:
            next_doc = dict(d)
            next_doc["case_id"] = None
            docs_items[i] = next_doc
            touched = True
    if touched:
        docs_data["items"] = docs_items
        _write_json(docs_path, docs_data)
    return True


def get_last_consultation_report_context(user_id: str, max_chars: int = 3000, subject_id: Optional[str] = None) -> str:
    """Контекст последнего отчёта (анамнез/выводы) для передачи в чат консьержа — определение специалиста и рекомендаций."""
    path = _user_dir(user_id) / "consultation_reports.json"
    data = _read_json(path)
    sid = normalize_subject_id(subject_id) if subject_id is not None else None
    reports = list(data.get("reports") or [])
    if sid is not None:
        reports = [r for r in reports if normalize_subject_id((r or {}).get("subject_id")) == sid]
    if not reports:
        return ""
    rep = (reports[-1].get("report") or {})
    parts = []
    if rep.get("case_summary"):
        parts.append(str(rep["case_summary"])[:1500])
    if rep.get("professional_summary"):
        parts.append(str(rep["professional_summary"])[:1500])
    if not parts and (rep.get("display_summary") or rep.get("user_summary")):
        parts.append(str(rep.get("display_summary") or rep.get("user_summary") or "")[:1500])
    return "\n\n".join(parts)[:max_chars] if parts else ""


def clear_all_consultation_reports(user_id: str, subject_id: Optional[str] = None) -> int:
    """Очистить всю историю рекомендаций (все отчёты). Возвращает число удалённых."""
    path = _user_dir(user_id) / "consultation_reports.json"
    data = _read_json(path)
    reports = list(data.get("reports") or [])
    sid = normalize_subject_id(subject_id) if subject_id is not None else None
    keep = [r for r in reports if (sid is not None and normalize_subject_id((r or {}).get("subject_id")) != sid)]
    if sid is None:
        keep = []
    count = len(reports) - len(keep)
    if count > 0:
        data["reports"] = keep
        _write_json(path, data)
    return count


def get_consultation_reports_list(user_id: str, include_deleted: bool = False, subject_id: Optional[str] = None) -> list:
    """Список отчётов консультаций для страницы «История рекомендаций»."""
    path = _user_dir(user_id) / "consultation_reports.json"
    data = _read_json(path)
    sid = normalize_subject_id(subject_id) if subject_id is not None else None
    reports = list(data.get("reports") or [])
    if sid is not None:
        reports = [r for r in reports if normalize_subject_id((r or {}).get("subject_id")) == sid]
    if not include_deleted:
        reports = [r for r in reports if not (r or {}).get("deleted_at")]
    items = []
    for r in reports:
        rep = r.get("report") or {}
        summary = (
            rep.get("display_summary")
            or rep.get("user_summary")
            or rep.get("case_summary")
            or rep.get("safe_next_steps")
            or ""
        )
        if isinstance(summary, list):
            summary = " ".join(str(s) for s in summary)[:200]
        else:
            summary = (summary or "")[:200]
        action_sequence = rep.get("action_sequence") if isinstance(rep.get("action_sequence"), dict) else None
        items.append({
            "id": r.get("id"),
            "created_at": r.get("created_at"),
            "severity": rep.get("severity_index") or "GREEN",
            "summary": summary,
            "title": rep.get("title"),
            "action_sequence": action_sequence,
            "deleted_at": r.get("deleted_at"),
        })
    return items


def get_consultation_reports_for_share(user_id: str, limit: int = 50) -> list:
    """
    Detailed consultation reports for doctor read-only shared view.
    Includes professional/case summaries to avoid losing clinical context.
    """
    path = _user_dir(user_id) / "consultation_reports.json"
    data = _read_json(path)
    reports = data.get("reports") or []
    out = []
    for r in reports[-max(1, int(limit)):]:
        rep = r.get("report") or {}
        out.append(
            {
                "id": r.get("id"),
                "created_at": r.get("created_at"),
                "severity": rep.get("severity_index") or "GREEN",
                "title": rep.get("title") or "",
                "summary": rep.get("display_summary") or rep.get("user_summary") or rep.get("safe_next_steps") or "",
                "case_summary": rep.get("case_summary") or "",
                "professional_summary": rep.get("professional_summary") or "",
                "safe_next_steps": rep.get("safe_next_steps") or "",
                "when_urgent": rep.get("when_urgent") or "",
                "diagnostics": rep.get("diagnostics") or [],
                "treatment": rep.get("treatment") or [],
                "nutrition": rep.get("nutrition") or [],
                "activity": rep.get("activity") or [],
                "action_sequence": rep.get("action_sequence") if isinstance(rep.get("action_sequence"), dict) else None,
            }
        )
    return out


def get_consultation_report_item(user_id: str, report_id: str, subject_id: Optional[str] = None) -> dict | None:
    path = _user_dir(user_id) / "consultation_reports.json"
    data = _read_json(path)
    sid = normalize_subject_id(subject_id) if subject_id is not None else None
    reports = list(data.get("reports") or [])
    if sid is not None:
        reports = [r for r in reports if normalize_subject_id((r or {}).get("subject_id")) == sid]
    target_id = str(report_id or "").strip()
    if not target_id:
        return None
    for r in reports:
        if str(r.get("id") or "") != target_id:
            continue
        rep = r.get("report") or {}
        summary = (
            rep.get("display_summary")
            or rep.get("user_summary")
            or rep.get("case_summary")
            or rep.get("safe_next_steps")
            or ""
        )
        if isinstance(summary, list):
            summary = " ".join(str(s) for s in summary)[:400]
        else:
            summary = str(summary or "")[:400]
        return {
            "id": r.get("id"),
            "created_at": r.get("created_at"),
            "severity": rep.get("severity_index") or "GREEN",
            "summary": summary,
            "title": rep.get("title"),
            "action_sequence": rep.get("action_sequence") if isinstance(rep.get("action_sequence"), dict) else None,
            "case_summary": rep.get("case_summary") or "",
            "professional_summary": rep.get("professional_summary") or "",
            "display_summary": rep.get("display_summary") or "",
            "user_summary": rep.get("user_summary") or "",
            "safe_next_steps": rep.get("safe_next_steps") or "",
            "when_urgent": rep.get("when_urgent") or "",
            "diagnostics": rep.get("diagnostics") or [],
            "treatment": rep.get("treatment") or [],
            "nutrition": rep.get("nutrition") or [],
            "activity": rep.get("activity") or [],
        }
    return None


def delete_consultation_report(user_id: str, report_id: str, subject_id: Optional[str] = None) -> bool:
    """Мягкое удаление отчёта: помечаем deleted_at. Можно вернуть через restore."""
    path = _user_dir(user_id) / "consultation_reports.json"
    data = _read_json(path)
    reports = list(data.get("reports") or [])
    target_id = str(report_id or "").strip()
    if not target_id:
        return False
    sid = normalize_subject_id(subject_id) if subject_id is not None else None
    for i, row in enumerate(reports):
        if str((row or {}).get("id") or "").strip() != target_id:
            continue
        if sid is not None and normalize_subject_id((row or {}).get("subject_id")) != sid:
            continue
        reports[i] = {**(row or {}), "deleted_at": time.time()}
        data["reports"] = reports
        _write_json(path, data)
        return True
    return False


def restore_consultation_report(user_id: str, report_id: str, subject_id: Optional[str] = None) -> bool:
    """Вернуть отчёт из корзины (снять deleted_at)."""
    path = _user_dir(user_id) / "consultation_reports.json"
    data = _read_json(path)
    reports = list(data.get("reports") or [])
    target_id = str(report_id or "").strip()
    if not target_id:
        return False
    sid = normalize_subject_id(subject_id) if subject_id is not None else None
    for i, row in enumerate(reports):
        if str((row or {}).get("id") or "").strip() != target_id:
            continue
        if sid is not None and normalize_subject_id((row or {}).get("subject_id")) != sid:
            continue
        next_row = {k: v for k, v in (row or {}).items() if k != "deleted_at"}
        reports[i] = next_row
        data["reports"] = reports
        _write_json(path, data)
        return True
    return False


def permanent_delete_consultation_report(user_id: str, report_id: str, subject_id: Optional[str] = None) -> bool:
    """Окончательно удалить отчёт из списка (для корзины)."""
    path = _user_dir(user_id) / "consultation_reports.json"
    data = _read_json(path)
    reports = list(data.get("reports") or [])
    target_id = str(report_id or "").strip()
    if not target_id:
        return False
    sid = normalize_subject_id(subject_id) if subject_id is not None else None
    for i, row in enumerate(reports):
        if str((row or {}).get("id") or "").strip() != target_id:
            continue
        if sid is not None and normalize_subject_id((row or {}).get("subject_id")) != sid:
            continue
        reports.pop(i)
        data["reports"] = reports
        _write_json(path, data)
        return True
    return False


def _purge_documents_older_than(user_id: str, max_age_sec: float) -> int:
    """Удаляет из списка документы с deleted_at старше max_age_sec. Возвращает число удалённых."""
    path = _user_dir(user_id) / "documents.json"
    data = _read_json(path)
    items = list(data.get("items") or [])
    now = time.time()
    keep = [it for it in items if not it.get("deleted_at") or (now - float(it.get("deleted_at") or 0)) < max_age_sec]
    removed = len(items) - len(keep)
    if removed > 0:
        data["items"] = keep
        _write_json(path, data)
    return removed


def _purge_reports_older_than(user_id: str, max_age_sec: float) -> int:
    """Удаляет из списка отчёты с deleted_at старше max_age_sec. Возвращает число удалённых."""
    path = _user_dir(user_id) / "consultation_reports.json"
    data = _read_json(path)
    reports = list(data.get("reports") or [])
    now = time.time()
    keep = []
    for row in reports:
        deleted_at = (row or {}).get("deleted_at")
        if not deleted_at or (now - float(deleted_at)) < max_age_sec:
            keep.append(row)
    removed = len(reports) - len(keep)
    if removed > 0:
        data["reports"] = keep
        _write_json(path, data)
    return removed


TRASH_DAYS = 30


def purge_deleted_older_than_30_days(user_id: str) -> dict:
    """Окончательно удаляет из корзины документы и отчёты старше 30 дней. Возвращает счётчики."""
    docs = _purge_documents_older_than(user_id, TRASH_DAYS * 24 * 3600)
    reports = _purge_reports_older_than(user_id, TRASH_DAYS * 24 * 3600)
    return {"documents": docs, "reports": reports}


def save_conversation_as_report(
    user_id: str,
    messages: list,
    title: Optional[str] = None,
    subject_id: Optional[str] = None,
) -> str:
    """
    Сохраняет диалог (голосовой или чат) как отчёт. Название — по жалобе и дате.
    messages: список dict с role ("user" | "assistant") и content (str).
    """
    user_id = get_or_create_user_id(user_id)
    if not messages:
        raise ValueError("messages is required and must not be empty")
    lines = []
    first_user_text = ""
    for m in messages:
        role = (m.get("role") or "").strip().lower()
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            lines.append("Пользователь: " + content)
            if not first_user_text:
                first_user_text = content[:200]
        else:
            lines.append("Ассистент: " + content)
    case_summary = "\n".join(lines)
    if not title and first_user_text:
        from datetime import datetime
        date_str = datetime.now().strftime("%d.%m.%Y")
        title = (first_user_text[:60].strip() + " … " + date_str) if len(first_user_text) > 60 else (first_user_text.strip() + " — " + date_str)
    if not title:
        from datetime import datetime
        title = "Диалог — " + datetime.now().strftime("%d.%m.%Y %H:%M")
    from app.services.report import DISCLAIMER_TEXT
    safe_next_steps = "Рекомендуется обратиться к врачу с собранным анамнезом и этим диалогом."
    when_urgent = "При появлении красных флагов (боль в груди, признаки инсульта, потеря сознания, сильная боль в животе, одышка и т.д.) — срочно обратитесь за помощью."
    report = {
        "title": title,
        "conversation_kind": "voice_chat",
        "case_summary": case_summary,
        "severity_index": "GREEN",
        "safe_next_steps": safe_next_steps,
        "when_urgent": when_urgent,
        "confidence": "Low",
        "disclaimer": DISCLAIMER_TEXT,
        "user_summary": safe_next_steps + " " + when_urgent,
        "professional_summary": "Диалог:\n" + case_summary + "\n\nРекомендации: " + safe_next_steps + "\nСрочно: " + when_urgent + "\n" + DISCLAIMER_TEXT,
    }
    return save_consultation_report(user_id, report, subject_id=subject_id)


def _retention_meta_path(user_id: str) -> Path:
    return _user_dir(user_id) / "conversation_retention_meta.json"


def _is_conversation_report(row: dict) -> bool:
    rep = (row or {}).get("report") or {}
    if rep.get("conversation_kind") == "voice_chat":
        return True
    ps = str(rep.get("professional_summary") or "").strip().lower()
    return ps.startswith("диалог:")


def _cleanup_conversation_reports_and_notify(user_id: str) -> None:
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "consultation_reports.json"
    data = _read_json(path)
    rows = list(data.get("reports") or [])
    if not rows:
        return
    meta_path = _retention_meta_path(user_id)
    meta = _read_json(meta_path)
    warnings_map = dict(meta.get("warnings") or {})
    now = time.time()
    keep_rows = []
    changed_reports = False
    changed_meta = False
    for row in rows:
        rid = str(row.get("id") or "")
        created = float(row.get("created_at") or now)
        age_days = int((now - created) // 86400)
        is_chat = _is_conversation_report(row)
        if is_chat and age_days >= CHAT_RETENTION_DAYS:
            changed_reports = True
            if rid in warnings_map:
                warnings_map.pop(rid, None)
                changed_meta = True
            continue
        keep_rows.append(row)
        if not is_chat or not rid:
            continue
        sent = set(int(x) for x in (warnings_map.get(rid) or []) if isinstance(x, int) or str(x).isdigit())
        warn_points = (
            (CHAT_WARN_DAY_1, "Через 3 дня чат-диалог будет удалён (храним 30 дней). "
                             "Если нужно, сохраните его: «История рекомендаций» -> «Экспорт истории болезни (PDF)»."),
            (CHAT_WARN_DAY_2, "Завтра чат-диалог будет удалён (храним 30 дней). "
                             "При необходимости скачайте PDF в «История рекомендаций»."),
        )
        for day, body in warn_points:
            if age_days >= day and day not in sent:
                add_notification(
                    user_id,
                    "Срок хранения чата",
                    body,
                    unread=True,
                    action={
                        "type": "export_chat_pdf",
                        "report_id": rid,
                    },
                )
                sent.add(day)
                changed_meta = True
        if sent:
            warnings_map[rid] = sorted(sent)

    if changed_reports:
        data["reports"] = keep_rows
        _write_json(path, data)
    if changed_meta:
        meta["warnings"] = warnings_map
        _write_json(meta_path, meta)


def enforce_chat_retention_policy(user_id: str) -> None:
    """Retention for chat-like conversation reports: 30 days + two pre-delete warnings."""
    try:
        _cleanup_conversation_reports_and_notify(user_id)
    except Exception as e:
        logger.warning("chat_retention_cleanup_failed", extra={"user_id": str(user_id), "error": str(e)})


def _parse_voice_diary_to_messages(text: str) -> list[dict[str, str]]:
    src = (text or "").strip()
    if not src:
        return []
    chunks = re.split(r"\n(?=\[\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}\]\n)", src)
    out: list[dict[str, str]] = []
    for chunk in chunks:
        block = chunk.strip()
        if not block:
            continue
        m = re.search(r"Вопрос:\s*(.*?)\nОтвет:\s*(.*)\Z", block, flags=re.S)
        if not m:
            continue
        q = re.sub(r"\s+", " ", (m.group(1) or "").strip())
        a = (m.group(2) or "").strip()
        if q:
            out.append({"role": "user", "content": q})
        if a:
            out.append({"role": "assistant", "content": a})
    return out[-100:]


def resume_chat_from_today_voice_diary(user_id: str, subject_id: Optional[str] = None) -> dict:
    user_id = get_or_create_user_id(user_id)
    sid = normalize_subject_id(subject_id)
    today_name = _voice_filename_by_date(time.time())
    docs = get_documents(user_id, subject_id=sid)
    diary_doc = None
    for d in reversed(docs):
        if (d.get("type") or "") == "voice_concierge" and (d.get("filename") or "") == today_name:
            diary_doc = d
            break
    if not diary_doc:
        return {"ok": False, "reason": "not_found", "messages_loaded": 0}
    messages = _parse_voice_diary_to_messages(diary_doc.get("extracted_text") or "")
    if not messages:
        return {"ok": False, "reason": "empty", "messages_loaded": 0}
    set_chat_history(user_id, messages, subject_id=sid)
    last_user = ""
    for m in reversed(messages):
        if (m.get("role") or "") == "user":
            last_user = m.get("content") or ""
            break
    return {
        "ok": True,
        "messages_loaded": len(messages),
        "last_user_message": last_user,
        "filename": diary_doc.get("filename") or "",
    }


def get_notifications(user_id: str) -> list:
    """Список напоминаний и уведомлений пользователя."""
    path = _user_dir(user_id) / "notifications.json"
    data = _read_json(path)
    items = data.get("items") or []
    return list(items)


def add_notification(
    user_id: str,
    title: str,
    body: Optional[str] = None,
    unread: bool = True,
    action: Optional[dict] = None,
) -> dict:
    """Добавить уведомление (например, после консультации с рекомендацией)."""
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "notifications.json"
    data = _read_json(path)
    items = data.get("items") or []
    title_s = (title or "").strip()
    body_s = (body or "").strip()
    body_key = body_s[:320] if len(body_s) > 320 else body_s
    now_ts = time.time()
    # Не дублировать то же уведомление за короткое время (фоновые запросы чата, повторные сессии).
    dedupe_sec = 6 * 3600
    for ex in reversed(items[-40:]):
        if (ex.get("title") or "").strip() != title_s:
            continue
        ex_body = (ex.get("body") or "").strip()
        ex_key = ex_body[:320] if len(ex_body) > 320 else ex_body
        if ex_key != body_key:
            continue
        try:
            ex_at = float(ex.get("created_at") or 0)
        except (TypeError, ValueError):
            ex_at = 0.0
        if now_ts - ex_at < dedupe_sec:
            return ex
    nid = str(uuid.uuid4())
    item = {
        "id": nid,
        "title": title,
        "body": (body or "").strip() or None,
        "created_at": round(time.time(), 2),
        "read": not unread,
    }
    if isinstance(action, dict) and action:
        item["action"] = action
    items.append(item)
    data["items"] = items[-200:]
    _write_json(path, data)
    return item


def mark_notifications_read(user_id: str, ids: Optional[list] = None) -> int:
    """Отметить уведомления как прочитанные. ids=None — все. Возвращает количество обновлённых."""
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "notifications.json"
    data = _read_json(path)
    items = data.get("items") or []
    target = set(ids) if ids else None
    count = 0
    for item in items:
        if item.get("read"):
            continue
        if target is None or (item.get("id") in target):
            item["read"] = True
            count += 1
    _write_json(path, data)
    return count


def clear_notifications(user_id: str) -> int:
    """Удалить все уведомления пользователя. Возвращает число удалённых записей."""
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "notifications.json"
    data = _read_json(path)
    items = data.get("items") or []
    n = len(items)
    data["items"] = []
    _write_json(path, data)
    return n


def get_calendar_reminders(user_id: str) -> list:
    """Список календарных напоминаний пользователя."""
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "calendar_reminders.json"
    data = _read_json(path)
    items = data.get("items") or []
    return list(items)


def add_calendar_reminder(
    user_id: str,
    title: str,
    schedule_time: str,
    *,
    frequency: str = "daily",
    payload: Optional[dict] = None,
    active: bool = True,
) -> dict:
    """Создать календарное напоминание с расписанием времени/частоты."""
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "calendar_reminders.json"
    data = _read_json(path)
    items = data.get("items") or []
    title_s = (title or "").strip() or "Напоминание"
    schedule_s = (schedule_time or "").strip() or "09:00"
    freq_s = (frequency or "").strip() or "daily"
    now_ts = round(time.time(), 2)

    # Мягкая дедупликация одинаковых активных напоминаний.
    for ex in reversed(items[-200:]):
        if not isinstance(ex, dict):
            continue
        if not bool(ex.get("active", True)):
            continue
        if (ex.get("title") or "").strip() != title_s:
            continue
        if (ex.get("schedule_time") or "").strip() != schedule_s:
            continue
        if (ex.get("frequency") or "").strip() != freq_s:
            continue
        return ex

    item = {
        "id": str(uuid.uuid4()),
        "title": title_s,
        "schedule_time": schedule_s,
        "frequency": freq_s,
        "active": bool(active),
        "created_at": now_ts,
        "updated_at": now_ts,
    }
    if isinstance(payload, dict) and payload:
        item["payload"] = payload
    items.append(item)
    data["items"] = items[-1000:]
    _write_json(path, data)
    return item


# ─── Кэш ответов консьержа (самообучение, быстрая реакция на похожие вопросы) ───
RESPONSE_CACHE_MAX_ENTRIES = 50


def _normalize_query_for_cache(q: str) -> str:
    """Нормализация запроса для поиска в кэше."""
    if not q or not isinstance(q, str):
        return ""
    s = re.sub(r"[^\w\sа-яёa-z0-9]", " ", q.strip().lower())
    return " ".join(w for w in s.split() if len(w) > 1)


def get_response_cache(user_id: str, query: str) -> Optional[dict]:
    """
    Ищет в кэше ответ на похожий вопрос. Возвращает dict с response, response_simple, query_orig
    или None. Используется для подстановки в контекст LLM (релевантный прошлый ответ).
    """
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "response_cache.json"
    data = _read_json(path)
    entries = data.get("entries") or []
    if not entries:
        return None
    norm = _normalize_query_for_cache(query)
    norm_tokens = set(norm.split()) if norm else set()
    if not norm_tokens:
        return None
    best = None
    best_score = 0
    for e in entries:
        en = (e.get("query_norm") or "").strip()
        if not en:
            continue
        et = set(en.split())
        overlap = len(norm_tokens & et) / max(len(norm_tokens), 1)
        if overlap >= 0.5 and overlap > best_score:
            best_score = overlap
            best = e
    if best is None:
        return None
    return {
        "query_orig": best.get("query_orig"),
        "response": best.get("response"),
        "response_simple": best.get("response_simple"),
    }


def save_to_response_cache(
    user_id: str,
    query: str,
    response: str,
    response_simple: Optional[str] = None,
) -> None:
    """Сохраняет пару вопрос–ответ в кэш для последующего использования при похожих вопросах."""
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "response_cache.json"
    data = _read_json(path)
    entries = list(data.get("entries") or [])
    norm = _normalize_query_for_cache(query)
    new_entry = {
        "query_norm": norm,
        "query_orig": (query or "")[:500],
        "response": (response or "")[:2000],
        "response_simple": (response_simple or "")[:1500] if response_simple else None,
        "ts": time.time(),
    }
    entries = [e for e in entries if e.get("query_norm") != norm]
    entries.append(new_entry)
    if len(entries) > RESPONSE_CACHE_MAX_ENTRIES:
        entries.sort(key=lambda x: x.get("ts") or 0)
        entries = entries[-RESPONSE_CACHE_MAX_ENTRIES:]
    data["entries"] = entries
    _write_json(path, data)


def _default_share_permissions(access_kind: str) -> dict[str, bool]:
    kind = str(access_kind or "").strip().lower()
    if kind == "family":
        return {
            "profile": True,
            "documents": False,
            "recommendations": True,
            "lab_cases": False,
            "voice_diary": False,
        }
    # doctor and fallback
    return {
        "profile": True,
        "documents": True,
        "recommendations": True,
        "lab_cases": True,
        "voice_diary": True,
    }


def _normalize_share_permissions(raw: Any, access_kind: str) -> dict[str, bool]:
    defaults = _default_share_permissions(access_kind)
    if not isinstance(raw, dict):
        return defaults
    out = dict(defaults)
    for k in ("profile", "documents", "recommendations", "lab_cases", "voice_diary"):
        if k in raw:
            out[k] = bool(raw.get(k))
    return out


def get_share_accesses(user_id: str, access_kind: Optional[str] = None) -> list:
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "share_access.json"
    data = _read_json(path)
    items = list(data.get("items") or [])
    now = time.time()
    active: list[dict] = []
    changed = False
    for it in items:
        if not isinstance(it, dict):
            changed = True
            continue
        if it.get("revoked"):
            # Keep history clean: revoked links are removed from visible list/storage.
            changed = True
            continue
        exp = float(it.get("expires_at") or 0)
        if exp and exp < now:
            # Auto-clean expired links to avoid confusion in the cabinet list.
            changed = True
            continue
        item = dict(it)
        kind = str(item.get("access_kind") or "doctor").strip().lower() or "doctor"
        item["access_kind"] = kind
        item["permissions"] = _normalize_share_permissions(item.get("permissions"), kind)
        item["one_time"] = bool(item.get("one_time"))
        try:
            item["session_minutes"] = max(5, min(int(item.get("session_minutes") or 30), 180))
        except Exception:
            item["session_minutes"] = 30
        if access_kind and kind != str(access_kind).strip().lower():
            continue
        active.append(item)
    if changed:
        data["items"] = active
        _write_json(path, data)
    return active


def create_share_access(
    user_id: str,
    label: str = "",
    doctor_name: str = "",
    days_valid: int = 30,
    one_time: bool = False,
    session_minutes: int = 30,
) -> dict:
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "share_access.json"
    data = _read_json(path)
    items = list(data.get("items") or [])
    now = round(time.time(), 2)
    days = max(1, min(int(days_valid or 30), 365))
    session_mins = max(5, min(int(session_minutes or 30), 180))
    item = {
        "id": str(uuid.uuid4()),
        "token": uuid.uuid4().hex,
        "label": (label or "").strip() or "Доступ для врача",
        "doctor_name": (doctor_name or "").strip() or "",
        "access_kind": "doctor",
        "member_name": "",
        "relation": "",
        "role": "doctor",
        "permissions": _default_share_permissions("doctor"),
        "one_time": bool(one_time),
        "session_minutes": session_mins,
        "activated_at": None,
        "access_count": 0,
        "last_access_at": None,
        "created_at": now,
        "expires_at": round(now + (days * 86400), 2),
        "revoked": False,
    }
    items.append(item)
    data["items"] = items[-100:]
    _write_json(path, data)
    return item


def create_family_access(
    user_id: str,
    *,
    member_name: str = "",
    relation: str = "",
    role: str = "family_viewer",
    permissions: Optional[dict] = None,
    days_valid: int = 30,
    one_time: bool = False,
    session_minutes: int = 30,
) -> dict:
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "share_access.json"
    data = _read_json(path)
    items = list(data.get("items") or [])
    active_family = [x for x in get_share_accesses(user_id, access_kind="family") if isinstance(x, dict)]
    if len(active_family) >= 5:
        raise ValueError("Лимит семейного доступа — 5 активных приглашений.")
    now = round(time.time(), 2)
    days = max(1, min(int(days_valid or 30), 365))
    session_mins = max(5, min(int(session_minutes or 30), 180))
    item = {
        "id": str(uuid.uuid4()),
        "token": uuid.uuid4().hex,
        "label": ("Семейный доступ: " + ((member_name or "").strip() or (relation or "").strip() or "участник")).strip(),
        "doctor_name": "",
        "access_kind": "family",
        "member_name": (member_name or "").strip()[:80],
        "relation": (relation or "").strip()[:40],
        "role": (role or "family_viewer").strip()[:40],
        "permissions": _normalize_share_permissions(permissions, "family"),
        "one_time": bool(one_time),
        "session_minutes": session_mins,
        "activated_at": None,
        "access_count": 0,
        "last_access_at": None,
        "created_at": now,
        "expires_at": round(now + (days * 86400), 2),
        "revoked": False,
    }
    items.append(item)
    data["items"] = items[-120:]
    _write_json(path, data)
    return item


def revoke_share_access(user_id: str, share_id: str) -> bool:
    user_id = get_or_create_user_id(user_id)
    path = _user_dir(user_id) / "share_access.json"
    data = _read_json(path)
    items = list(data.get("items") or [])
    out = []
    removed = False
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("id") == share_id:
            removed = True
            continue
        out.append(it)
    if removed:
        data["items"] = out
        _write_json(path, data)
    return removed


def _is_share_valid(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("revoked"):
        return False
    exp = float(item.get("expires_at") or 0)
    if exp and exp < time.time():
        return False
    if bool(item.get("one_time")):
        try:
            activated_at = float(item.get("activated_at") or 0)
        except Exception:
            activated_at = 0.0
        if activated_at > 0:
            try:
                session_minutes = max(5, min(int(item.get("session_minutes") or 30), 180))
            except Exception:
                session_minutes = 30
            if (time.time() - activated_at) > (session_minutes * 60):
                return False
    return bool(item.get("token"))


def _build_user_shared_snapshot(user_id: str, permissions: Optional[dict] = None) -> dict:
    perms = _normalize_share_permissions(permissions or {}, "doctor")
    profile = get_profile(user_id)
    docs = get_documents(user_id)
    recs = get_consultation_reports_for_share(user_id, limit=50)
    lab_cases = get_lab_cases(user_id)
    now = time.localtime()
    today_name = "voice_concierge_" + time.strftime("%Y-%m-%d", now) + ".txt"
    voice_diary = None
    for d in reversed(docs):
        if (d.get("type") or "") == "voice_concierge" and (d.get("filename") or "") == today_name:
            voice_diary = {
                "id": d.get("id"),
                "filename": d.get("filename"),
                "summary": d.get("summary"),
                "created_at": d.get("created_at"),
                "extracted_text": d.get("extracted_text") or "",
            }
            break
    return {
        "profile": profile if perms.get("profile") else {},
        "documents": ([
            {
                "id": d.get("id"),
                "type": d.get("type"),
                "filename": d.get("filename"),
                "summary": d.get("summary"),
                "created_at": d.get("created_at"),
                "case_id": d.get("case_id"),
                "extracted_text": (d.get("extracted_text") or "")[:5000],
            }
            for d in docs[-50:]
        ] if perms.get("documents") else []),
        "lab_cases": ([
            {
                "id": c.get("id"),
                "name": c.get("name"),
                "created_at": c.get("created_at"),
                "updated_at": c.get("updated_at"),
            }
            for c in lab_cases[-50:]
            if isinstance(c, dict)
        ] if perms.get("lab_cases") else []),
        "recommendations": recs[-50:] if perms.get("recommendations") else [],
        "voice_diary_today": voice_diary if perms.get("voice_diary") else None,
    }


def get_shared_snapshot_by_token(token: str) -> dict | None:
    tok = (token or "").strip()
    if not tok:
        return None
    if not _DATA_ROOT.exists():
        return None
    for user_dir in _DATA_ROOT.iterdir():
        if not user_dir.is_dir():
            continue
        data = _read_json(user_dir / "share_access.json")
        items = list(data.get("items") or [])
        changed = False
        for idx, it in enumerate(items):
            if (it.get("token") or "") != tok:
                continue
            if not _is_share_valid(it):
                return None
            now = round(time.time(), 2)
            mutable = dict(it)
            if bool(mutable.get("one_time")) and not mutable.get("activated_at"):
                mutable["activated_at"] = now
                changed = True
            mutable["access_count"] = int(mutable.get("access_count") or 0) + 1
            mutable["last_access_at"] = now
            if mutable != it:
                items[idx] = mutable
                changed = True
                it = mutable
            if changed:
                data["items"] = items
                _write_json(user_dir / "share_access.json", data)
            user_id = user_dir.name
            kind = str(it.get("access_kind") or "doctor").strip().lower() or "doctor"
            perms = _normalize_share_permissions(it.get("permissions"), kind)
            snap = _build_user_shared_snapshot(user_id, perms)
            return {
                "share": {
                    "id": it.get("id"),
                    "label": it.get("label"),
                    "doctor_name": it.get("doctor_name"),
                    "access_kind": kind,
                    "member_name": it.get("member_name") or "",
                    "relation": it.get("relation") or "",
                    "role": it.get("role") or "",
                    "permissions": perms,
                    "created_at": it.get("created_at"),
                    "expires_at": it.get("expires_at"),
                },
                "user_id": user_id,
                "snapshot": snap,
            }
    return None


def _voice_case_name_by_date(ts: Optional[float] = None) -> str:
    dt = time.localtime(ts or time.time())
    return "Консьерж " + time.strftime("%d.%m.%Y", dt)


def _voice_filename_by_date(ts: Optional[float] = None) -> str:
    dt = time.localtime(ts or time.time())
    return "voice_concierge_" + time.strftime("%Y-%m-%d", dt) + ".txt"


def _get_or_create_voice_case(user_id: str, ts: Optional[float] = None, subject_id: Optional[str] = None) -> dict:
    target = _voice_case_name_by_date(ts)
    for c in get_lab_cases(user_id, subject_id=subject_id):
        if (c.get("name") or "") == target:
            return c
    return create_lab_case(user_id, target, subject_id=subject_id)


def save_voice_concierge_turn_to_labs(
    user_id: str,
    user_message: str,
    assistant_response: str,
    *,
    ts: Optional[float] = None,
    subject_id: Optional[str] = None,
) -> dict:
    """
    Persist every voice concierge turn in Analyses folder by date:
    - creates/uses case "Консьерж DD.MM.YYYY"
    - creates/updates text document with full Q/A history for that date
    """
    user_id = get_or_create_user_id(user_id)
    now_ts = float(ts or time.time())
    sid = normalize_subject_id(subject_id)
    case_item = _get_or_create_voice_case(user_id, now_ts, subject_id=sid)
    case_id = case_item.get("id")
    filename = _voice_filename_by_date(now_ts)
    q = (user_message or "").strip()
    a = (assistant_response or "").strip()
    stamp = time.strftime("%d.%m.%Y %H:%M", time.localtime(now_ts))
    block = f"[{stamp}]\nВопрос: {q}\nОтвет: {a}\n\n"

    docs = get_documents(user_id, subject_id=sid)
    target = None
    for d in docs:
        if (d.get("type") or "") != "voice_concierge":
            continue
        if (d.get("case_id") or "") != (case_id or ""):
            continue
        if (d.get("filename") or "") == filename:
            target = d
            break

    if target:
        prev_text = (target.get("extracted_text") or "")
        next_text = (prev_text + block).strip()[:50000]
        updated = update_document(
            user_id,
            target.get("id") or "",
            {
                "extracted_text": next_text,
                "summary": "Лог диалога голосового консьержа за " + _voice_case_name_by_date(now_ts).replace("Консьерж ", ""),
                "filename": filename,
                "case_id": case_id,
                "type": "voice_concierge",
                "subject_id": sid,
            },
        )
        return updated or target

    add_document(
        user_id,
        {
            "id": str(uuid.uuid4()),
            "type": "voice_concierge",
            "summary": "Лог диалога голосового консьержа за " + _voice_case_name_by_date(now_ts).replace("Консьерж ", ""),
            "created_at": now_ts,
            "filename": filename,
            "extracted_text": block[:50000],
            "case_id": case_id,
            "subject_id": sid,
        },
    )
    docs_after = get_documents(user_id, subject_id=sid)
    return docs_after[-1] if docs_after else {}
