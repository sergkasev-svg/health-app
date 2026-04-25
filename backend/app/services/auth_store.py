"""
Simple auth store for login/password (email or phone) with session tokens.
Двухуровневый доступ: пользователь (свой пароль) и администратор (мастер-пароль).
Роль сохраняется в сессии; у пользователя админ может отключать функции (disabled_features).
Data is stored in backend/data/auth/*.json
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from pathlib import Path
from typing import Optional

try:
    from webauthn import (
        options_to_json,
        generate_registration_options,
        verify_registration_response,
        generate_authentication_options,
        verify_authentication_response,
    )
    from webauthn.helpers.structs import (
        PublicKeyCredentialDescriptor,
        AuthenticatorSelectionCriteria,
        UserVerificationRequirement,
    )
    _PASSKEY_AVAILABLE = True
except Exception:
    _PASSKEY_AVAILABLE = False


_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_AUTH_DIR = _BACKEND_DIR / "data" / "auth"
_ACCOUNTS_FILE = _AUTH_DIR / "accounts.json"
_SESSIONS_FILE = _AUTH_DIR / "sessions.json"
_PASSKEY_CHALLENGES_FILE = _AUTH_DIR / "passkey_challenges.json"

_SESSION_TTL_SEC = 60 * 60 * 24 * 30  # 30 days
_PASSKEY_CHALLENGE_TTL_SEC = 60 * 5
_DEFAULT_RP_NAME = "Health App"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now() -> float:
    return round(time.time(), 2)


def _norm_email(s: str) -> str:
    return (s or "").strip().lower()


def _norm_phone(s: str) -> str:
    raw = "".join(ch for ch in (s or "") if ch.isdigit() or ch == "+")
    if raw.startswith("8") and len(raw) == 11:
        raw = "+7" + raw[1:]
    if raw.startswith("7") and len(raw) == 11:
        raw = "+" + raw
    if raw and raw[0] != "+":
        raw = "+" + raw
    return raw


def normalize_login(login: str) -> tuple[str, str]:
    val = (login or "").strip()
    if "@" in val:
        em = _norm_email(val)
        if not em or "." not in em.split("@")[-1]:
            raise ValueError("Некорректный email.")
        return "email", em
    ph = _norm_phone(val)
    if len("".join(ch for ch in ph if ch.isdigit())) < 10:
        raise ValueError("Некорректный номер телефона.")
    return "phone", ph


def _hash_password(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return digest.hex()


def _new_password_record(password: str) -> dict:
    if len(password or "") < 8:
        raise ValueError("Пароль должен быть не короче 8 символов.")
    salt_hex = secrets.token_hex(16)
    return {"salt": salt_hex, "hash": _hash_password(password, salt_hex)}


def _verify_password(password: str, rec: dict) -> bool:
    if not rec:
        return False
    got = _hash_password(password or "", str(rec.get("salt") or ""))
    return hmac.compare_digest(got, str(rec.get("hash") or ""))


def _accounts_data() -> dict:
    data = _read_json(_ACCOUNTS_FILE)
    if "items" not in data:
        data["items"] = []
    return data


def _sessions_data() -> dict:
    data = _read_json(_SESSIONS_FILE)
    if "items" not in data:
        data["items"] = []
    return data


def _passkey_challenges_data() -> dict:
    data = _read_json(_PASSKEY_CHALLENGES_FILE)
    if "items" not in data:
        data["items"] = []
    return data


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    s = (data or "").strip()
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))


def _passkey_supported() -> None:
    if not _PASSKEY_AVAILABLE:
        raise ValueError("Passkey не настроен на сервере. Установите зависимость webauthn.")


def _get_account_by_normalized_login(normalized: str) -> Optional[dict]:
    data = _accounts_data()
    for it in list(data.get("items") or []):
        if it.get("login_normalized") == normalized:
            return it
    return None


def _get_account_by_user_id(user_id: str) -> Optional[dict]:
    data = _accounts_data()
    for it in list(data.get("items") or []):
        if it.get("id") == user_id:
            return it
    return None


def _save_account(updated_account: dict) -> None:
    data = _accounts_data()
    items = list(data.get("items") or [])
    for i, it in enumerate(items):
        if it.get("id") == updated_account.get("id"):
            items[i] = updated_account
            data["items"] = items
            _write_json(_ACCOUNTS_FILE, data)
            return
    raise ValueError("Пользователь не найден.")


def _cleanup_challenges() -> list[dict]:
    now = _now()
    cdata = _passkey_challenges_data()
    items = list(cdata.get("items") or [])
    alive = [x for x in items if float(x.get("expires_at") or 0) > now]
    if len(alive) != len(items):
        cdata["items"] = alive
        _write_json(_PASSKEY_CHALLENGES_FILE, cdata)
    return alive


def _store_challenge(flow: dict) -> None:
    alive = _cleanup_challenges()
    alive.append(flow)
    _write_json(_PASSKEY_CHALLENGES_FILE, {"items": alive[-500:]})


def _pop_challenge(flow_id: str, kind: str) -> Optional[dict]:
    cdata = _passkey_challenges_data()
    items = list(cdata.get("items") or [])
    now = _now()
    found = None
    alive = []
    for it in items:
        if float(it.get("expires_at") or 0) <= now:
            continue
        if not found and it.get("flow_id") == flow_id and it.get("kind") == kind:
            found = it
            continue
        alive.append(it)
    cdata["items"] = alive
    _write_json(_PASSKEY_CHALLENGES_FILE, cdata)
    return found


def register_user(login: str, password: str, *, name: str = "") -> dict:
    kind, normalized = normalize_login(login)
    data = _accounts_data()
    items = list(data.get("items") or [])
    for it in items:
        if it.get("login_normalized") == normalized:
            raise ValueError("Пользователь с таким логином уже существует.")
    user_id = "u_" + uuid.uuid4().hex[:24]
    pass_rec = _new_password_record(password)
    item = {
        "id": user_id,
        "login_kind": kind,
        "login_normalized": normalized,
        "display_login": login.strip(),
        "name": (name or "").strip(),
        "password": pass_rec,
        "created_at": _now(),
        "updated_at": _now(),
    }
    items.append(item)
    data["items"] = items
    _write_json(_ACCOUNTS_FILE, data)
    return {"user_id": user_id, "login_kind": kind, "login": normalized}


def _get_master_password() -> str:
    try:
        from app.config import get_settings
        return get_settings().admin_master_password or ""
    except Exception:
        return ""


def authenticate_user(login: str, password: str) -> dict:
    """
    Проверяет логин и пароль. Уровень доступа определяется паролем:
    - пароль аккаунта → роль user (доступ к пользовательскому набору функций);
    - мастер-пароль (если задан) → роль admin (полный доступ).
    """
    _, normalized = normalize_login(login)
    data = _accounts_data()
    for it in list(data.get("items") or []):
        if it.get("login_normalized") != normalized:
            continue
        # Сначала проверка обычного пароля
        if _verify_password(password, it.get("password") or {}):
            return {
                "user_id": it.get("id") or "",
                "login_kind": it.get("login_kind") or "",
                "login": it.get("login_normalized") or "",
                "name": it.get("name") or "",
                "role": "user",
            }
        # Затем проверка мастер-пароля для входа как администратор
        master = _get_master_password()
        if master and password == master:
            return {
                "user_id": it.get("id") or "",
                "login_kind": it.get("login_kind") or "",
                "login": it.get("login_normalized") or "",
                "name": it.get("name") or "",
                "role": "admin",
            }
        break
    raise ValueError("Неверный логин или пароль.")


def begin_passkey_registration(login: str, password: str, *, origin: str, rp_id: str) -> dict:
    _passkey_supported()
    user = authenticate_user(login, password)
    account = _get_account_by_user_id(user["user_id"])
    if not account:
        raise ValueError("Пользователь не найден.")
    passkeys = list(account.get("passkeys") or [])
    exclude = []
    for pk in passkeys:
        cid = str(pk.get("credential_id") or "").strip()
        if not cid:
            continue
        exclude.append(PublicKeyCredentialDescriptor(id=_b64url_decode(cid)))
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=_DEFAULT_RP_NAME,
        user_id=user["user_id"].encode("utf-8"),
        user_name=user["login"],
        user_display_name=account.get("name") or user["login"],
        exclude_credentials=exclude,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.PREFERRED
        ),
    )
    options_dict = json.loads(options_to_json(options))
    challenge = str(options_dict.get("challenge") or "")
    flow_id = secrets.token_urlsafe(24)
    _store_challenge(
        {
            "flow_id": flow_id,
            "kind": "register",
            "user_id": user["user_id"],
            "challenge": challenge,
            "origin": origin,
            "rp_id": rp_id,
            "expires_at": round(_now() + _PASSKEY_CHALLENGE_TTL_SEC, 2),
        }
    )
    return {"flow_id": flow_id, "public_key": options_dict}


def finish_passkey_registration(flow_id: str, credential: dict) -> dict:
    _passkey_supported()
    flow = _pop_challenge((flow_id or "").strip(), "register")
    if not flow:
        raise ValueError("Сессия регистрации отпечатка истекла. Повторите.")
    user_id = str(flow.get("user_id") or "")
    account = _get_account_by_user_id(user_id)
    if not account:
        raise ValueError("Пользователь не найден.")
    try:
        ver = verify_registration_response(
            credential=credential,
            expected_challenge=_b64url_decode(str(flow.get("challenge") or "")),
            expected_origin=str(flow.get("origin") or ""),
            expected_rp_id=str(flow.get("rp_id") or ""),
            require_user_verification=False,
        )
    except Exception as e:
        raise ValueError("Не удалось зарегистрировать отпечаток: " + str(e))
    passkeys = list(account.get("passkeys") or [])
    new_cred_id = _b64url_encode(ver.credential_id)
    for pk in passkeys:
        if pk.get("credential_id") == new_cred_id:
            raise ValueError("Этот отпечаток уже зарегистрирован.")
    passkeys.append(
        {
            "id": "pk_" + uuid.uuid4().hex[:16],
            "credential_id": new_cred_id,
            "public_key": _b64url_encode(ver.credential_public_key),
            "sign_count": int(ver.sign_count or 0),
            "created_at": _now(),
        }
    )
    nxt = dict(account)
    nxt["passkeys"] = passkeys[-20:]
    nxt["updated_at"] = _now()
    _save_account(nxt)
    return {"ok": True, "count": len(nxt["passkeys"])}


def begin_passkey_login(login: str, *, origin: str, rp_id: str) -> dict:
    _passkey_supported()
    _, normalized = normalize_login(login)
    account = _get_account_by_normalized_login(normalized)
    if not account:
        raise ValueError("Пользователь не найден.")
    passkeys = list(account.get("passkeys") or [])
    descriptors = []
    for pk in passkeys:
        cid = str(pk.get("credential_id") or "").strip()
        if not cid:
            continue
        descriptors.append(PublicKeyCredentialDescriptor(id=_b64url_decode(cid)))
    if not descriptors:
        raise ValueError("Для этого аккаунта не настроен вход по отпечатку.")
    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=descriptors,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    options_dict = json.loads(options_to_json(options))
    challenge = str(options_dict.get("challenge") or "")
    flow_id = secrets.token_urlsafe(24)
    _store_challenge(
        {
            "flow_id": flow_id,
            "kind": "login",
            "user_id": account.get("id"),
            "challenge": challenge,
            "origin": origin,
            "rp_id": rp_id,
            "expires_at": round(_now() + _PASSKEY_CHALLENGE_TTL_SEC, 2),
        }
    )
    return {"flow_id": flow_id, "public_key": options_dict}


def finish_passkey_login(flow_id: str, credential: dict) -> dict:
    _passkey_supported()
    flow = _pop_challenge((flow_id or "").strip(), "login")
    if not flow:
        raise ValueError("Сессия входа по отпечатку истекла. Повторите.")
    user_id = str(flow.get("user_id") or "")
    account = _get_account_by_user_id(user_id)
    if not account:
        raise ValueError("Пользователь не найден.")
    passkeys = list(account.get("passkeys") or [])
    cred_id = str((credential or {}).get("id") or "")
    target = None
    for pk in passkeys:
        if pk.get("credential_id") == cred_id:
            target = pk
            break
    if not target:
        raise ValueError("Неизвестный отпечаток для этого аккаунта.")
    try:
        ver = verify_authentication_response(
            credential=credential,
            expected_challenge=_b64url_decode(str(flow.get("challenge") or "")),
            expected_origin=str(flow.get("origin") or ""),
            expected_rp_id=str(flow.get("rp_id") or ""),
            credential_public_key=_b64url_decode(str(target.get("public_key") or "")),
            credential_current_sign_count=int(target.get("sign_count") or 0),
            require_user_verification=False,
        )
    except Exception as e:
        raise ValueError("Не удалось выполнить вход по отпечатку: " + str(e))
    target["sign_count"] = int(ver.new_sign_count or target.get("sign_count") or 0)
    nxt = dict(account)
    nxt["passkeys"] = passkeys
    nxt["updated_at"] = _now()
    _save_account(nxt)
    sess = create_session(user_id, role="user")
    return {
        "ok": True,
        "user_id": user_id,
        "login_kind": account.get("login_kind") or "",
        "login": account.get("login_normalized") or "",
        "name": account.get("name") or "",
        "token": sess["token"],
        "expires_at": sess["expires_at"],
    }


def disable_passkeys(user_id: str) -> int:
    account = _get_account_by_user_id(user_id or "")
    if not account:
        raise ValueError("Пользователь не найден.")
    current = list(account.get("passkeys") or [])
    if not current:
        return 0
    nxt = dict(account)
    nxt["passkeys"] = []
    nxt["updated_at"] = _now()
    _save_account(nxt)
    return len(current)


def create_session(user_id: str, role: str = "user") -> dict:
    role = "admin" if (role or "").strip().lower() == "admin" else "user"
    token = secrets.token_urlsafe(36)
    now = _now()
    sess = {
        "token": token,
        "user_id": user_id,
        "role": role,
        "created_at": now,
        "expires_at": round(now + _SESSION_TTL_SEC, 2),
    }
    data = _sessions_data()
    items = [s for s in list(data.get("items") or []) if s.get("expires_at", 0) > now]
    items.append(sess)
    data["items"] = items[-2000:]
    _write_json(_SESSIONS_FILE, data)
    return sess


def get_user_by_session(token: str) -> Optional[dict]:
    tok = (token or "").strip()
    if not tok:
        return None
    now = _now()
    sdata = _sessions_data()
    items = list(sdata.get("items") or [])
    found = None
    alive = []
    for s in items:
        if float(s.get("expires_at") or 0) <= now:
            continue
        alive.append(s)
        if s.get("token") == tok:
            found = s
    if len(alive) != len(items):
        sdata["items"] = alive
        _write_json(_SESSIONS_FILE, sdata)
    if not found:
        return None
    uid = found.get("user_id") or ""
    role = found.get("role") or "user"
    adata = _accounts_data()
    for it in list(adata.get("items") or []):
        if it.get("id") == uid:
            disabled = list(it.get("disabled_features") or [])
            return {
                "user_id": uid,
                "login_kind": it.get("login_kind") or "",
                "login": it.get("login_normalized") or "",
                "name": it.get("name") or "",
                "role": role,
                "disabled_features": disabled,
            }
    return None


def revoke_session(token: str) -> None:
    tok = (token or "").strip()
    if not tok:
        return
    data = _sessions_data()
    items = [s for s in list(data.get("items") or []) if s.get("token") != tok]
    data["items"] = items
    _write_json(_SESSIONS_FILE, data)


# Ключи функций ЛК: пользовательский набор по умолчанию; админ видит все + админ-разделы.
USER_DEFAULT_FEATURES = [
    "dashboard", "personal-cabinet", "symptoms", "labs", "health", "profile", "settings",
    "find-doctor", "recommendations-history", "trash", "notifications", "offline-guide",
    "reports-docs", "privacy",
]
ADMIN_ONLY_FEATURES = [
    "review-queue", "analytics", "cluster-workspace", "admin-users",
]
ALL_FEATURE_KEYS = USER_DEFAULT_FEATURES + ADMIN_ONLY_FEATURES


def get_enabled_features(role: str, disabled_features: list[str]) -> list[str]:
    """Список включённых функций: для admin — все, для user — USER_DEFAULT_FEATURES минус disabled_features."""
    disabled_set = {str(x).strip() for x in (disabled_features or []) if str(x).strip()}
    if (role or "").strip().lower() == "admin":
        return [k for k in ALL_FEATURE_KEYS if k not in disabled_set]
    base = [k for k in USER_DEFAULT_FEATURES if k not in disabled_set]
    return base


def list_accounts() -> list[dict]:
    """Список аккаунтов (для админа): id, login, name, disabled_features."""
    data = _accounts_data()
    out = []
    for it in list(data.get("items") or []):
        out.append({
            "id": it.get("id") or "",
            "login": it.get("display_login") or it.get("login_normalized") or "",
            "name": (it.get("name") or "").strip(),
            "disabled_features": list(it.get("disabled_features") or []),
        })
    return out


def set_user_disabled_features(user_id: str, disabled_features: list[str]) -> dict:
    """Задать отключённые функции для пользователя (только для вызова от админа)."""
    data = _accounts_data()
    items = list(data.get("items") or [])
    for i, it in enumerate(items):
        if it.get("id") == user_id:
            cleaned = [str(x).strip() for x in (disabled_features or []) if str(x).strip() and str(x).strip() in ALL_FEATURE_KEYS]
            nxt = dict(it)
            nxt["disabled_features"] = cleaned
            nxt["updated_at"] = _now()
            items[i] = nxt
            data["items"] = items
            _write_json(_ACCOUNTS_FILE, data)
            return {"user_id": user_id, "disabled_features": nxt["disabled_features"]}
    raise ValueError("Пользователь не найден.")


def change_password(user_id: str, old_password: str, new_password: str) -> None:
    data = _accounts_data()
    items = list(data.get("items") or [])
    for i, it in enumerate(items):
        if it.get("id") != user_id:
            continue
        if not _verify_password(old_password, it.get("password") or {}):
            raise ValueError("Текущий пароль неверный.")
        rec = _new_password_record(new_password)
        nxt = dict(it)
        nxt["password"] = rec
        nxt["updated_at"] = _now()
        items[i] = nxt
        data["items"] = items
        _write_json(_ACCOUNTS_FILE, data)
        return
    raise ValueError("Пользователь не найден.")
