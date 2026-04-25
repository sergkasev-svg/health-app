"""
TTS providers: Edge TTS, Yandex SpeechKit, local Piper, or local XTTS sidecar.
"""
import asyncio
import logging
import re
import time
from typing import Any, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

YANDEX_TTS_URL = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
# Голос Михаила для Yandex — мужской русский (filipp)
YANDEX_MIKHAIL_VOICE = "filipp"
YANDEX_VOICE_FRIENDLY = "Yandex SpeechKit — Филипп (RU, мужской)"
LOCAL_MIKHAIL_VOICE_ID = "ru_RU-ruslan-medium"
LOCAL_MIKHAIL_VOICE_FRIENDLY = "Piper Ruslan (RU, male, velvet)"
LOCAL_XTTS_VOICE_ID = "xtts_mikhail_clone"
LOCAL_XTTS_FRIENDLY = "XTTS v2 Mikhail clone (RU, high-quality)"

EDGE_TTS_TIMEOUT_SEC = 10


class TTSProviderError(RuntimeError):
    pass


_VOICE_CACHE: list[dict[str, Any]] = []
_VOICE_CACHE_TS: float = 0.0
_VOICE_CACHE_TTL_SEC = 6 * 60 * 60  # 6 hours


def _normalize_rate(rate: Optional[str]) -> str:
    if rate is None:
        return "+0%"
    txt = str(rate).strip()
    if not txt:
        return "+0%"
    # Accept values like +20%, -10%, 15
    m = re.fullmatch(r"([+-]?\d{1,3})%?", txt)
    if not m:
        return "+0%"
    val = int(m.group(1))
    val = max(-50, min(150, val))
    return f"{val:+d}%"


def _normalize_local_rate(rate: Optional[str]) -> str:
    """
    Local Piper tends to sound too fast with web speed presets tuned for cloud TTS.
    Compress frontend rate delta to a gentler range (avoid sounding sluggish on prod).
    """
    base = _normalize_rate(rate)
    try:
        val = int(base.replace("%", ""))
    except ValueError:
        val = 0
    # Light baseline + compressed delta — was -4% at neutral and felt "тормозит" on VPS.
    val = int(round(val * 0.35)) - 1
    val = max(-22, min(18, val))
    return f"{val:+d}%"


def get_tts_client_provider_label() -> str:
    """
    Provider id for the frontend (voice.js): must match server-side synthesis path.
    """
    settings = get_settings()
    p = (settings.tts_provider or "auto").strip().lower() or "auto"
    if p == "local":
        return "local_tts"
    if p == "local_xtts":
        return "local_xtts"
    if p == "yandex":
        return "yandex"
    if p == "edge_tts":
        return "edge_tts"
    return "auto"


def _soften_for_local_tts(text: str) -> str:
    """
    Local voices over-react to aggressive punctuation shaping.
    Keep phrasing natural and reduce long synthetic pauses.
    """
    t = (text or "").strip()
    if not t:
        return ""
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"\n+", " ", t)
    t = re.sub(r"\s*[–—]\s*", " ", t)
    t = re.sub(r"\s*;\s*", ", ", t)
    t = re.sub(r"\s*:\s*", ", ", t)
    t = re.sub(r"\s*-\s+", " ", t)
    t = re.sub(r"\s*,\s*,+", ", ", t)
    t = re.sub(r",\s*,", ", ", t)
    t = re.sub(r"\.{2,}", ".", t)
    t = re.sub(r"([!?]){2,}", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t


def _voice_sort_key(v: dict[str, Any]) -> tuple[int, int, int, str]:
    locale = str(v.get("locale") or "").lower()
    gender = str(v.get("gender") or "").lower()
    name = str(v.get("name") or "").lower()
    ru_rank = 0 if locale.startswith("ru") else 1
    male_rank = 0 if gender == "male" else 1
    neural_rank = 0 if "neural" in name else 1
    return (ru_rank, male_rank, neural_rank, name)


def _default_voice(voices: list[dict[str, Any]]) -> Optional[str]:
    if not voices:
        return None
    # Prefer Russian male neural voice.
    for v in voices:
        locale = str(v.get("locale") or "").lower()
        gender = str(v.get("gender") or "").lower()
        name = str(v.get("name") or "").lower()
        if locale.startswith("ru") and gender == "male" and "neural" in name:
            return v.get("id")
    for v in voices:
        locale = str(v.get("locale") or "").lower()
        gender = str(v.get("gender") or "").lower()
        if locale.startswith("ru") and gender == "male":
            return v.get("id")
    return voices[0].get("id")


# Единственный голос консьержа — Михаил (Microsoft Dmitry Online Natural, ru-RU, male).
MIKHAIL_VOICE_ID = "ru-RU-DmitryNeural"
MIKHAIL_VOICE_FRIENDLY = "Microsoft Dmitry Online (Natural) - Russian (Russia) (ru-RU / male)"


async def get_tts_voices(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Return one stable concierge voice for current configured provider."""
    global _VOICE_CACHE, _VOICE_CACHE_TS
    now = time.time()
    if _VOICE_CACHE and (not force_refresh) and (now - _VOICE_CACHE_TS < _VOICE_CACHE_TTL_SEC):
        return _VOICE_CACHE
    settings = get_settings()
    provider_setting = (settings.tts_provider or "auto").strip().lower() or "auto"
    if provider_setting == "local":
        local_voice = settings.local_tts_voice_id or LOCAL_MIKHAIL_VOICE_ID
        _VOICE_CACHE = [
            {
                "id": local_voice,
                "name": local_voice,
                "locale": "ru-RU",
                "gender": "male",
                "friendly_name": LOCAL_MIKHAIL_VOICE_FRIENDLY,
                "provider": "local_tts",
            }
        ]
    elif provider_setting == "local_xtts":
        _VOICE_CACHE = [
            {
                "id": LOCAL_XTTS_VOICE_ID,
                "name": LOCAL_XTTS_VOICE_ID,
                "locale": "ru-RU",
                "gender": "male",
                "friendly_name": LOCAL_XTTS_FRIENDLY,
                "provider": "local_xtts",
            }
        ]
    elif provider_setting == "yandex":
        _VOICE_CACHE = [
            {
                "id": f"yandex:{YANDEX_MIKHAIL_VOICE}",
                "name": YANDEX_MIKHAIL_VOICE,
                "locale": "ru-RU",
                "gender": "male",
                "friendly_name": YANDEX_VOICE_FRIENDLY,
                "provider": "yandex",
            }
        ]
    elif provider_setting == "edge_tts":
        _VOICE_CACHE = [
            {
                "id": MIKHAIL_VOICE_ID,
                "name": MIKHAIL_VOICE_ID,
                "locale": "ru-RU",
                "gender": "male",
                "friendly_name": MIKHAIL_VOICE_FRIENDLY,
                "provider": "edge_tts",
            }
        ]
    else:
        # auto: Edge first at runtime; UI shows the same primary voice label.
        _VOICE_CACHE = [
            {
                "id": MIKHAIL_VOICE_ID,
                "name": MIKHAIL_VOICE_ID,
                "locale": "ru-RU",
                "gender": "male",
                "friendly_name": MIKHAIL_VOICE_FRIENDLY,
                "provider": "auto",
            }
        ]
    _VOICE_CACHE_TS = now
    return _VOICE_CACHE


def _line_needs_terminal_punct(line: str) -> bool:
    s = (line or "").strip()
    if len(s) < 2:
        return False
    return not re.search(r"[.!?…:;]$", s)


def _inject_soft_pauses_without_punctuation(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return s
    if re.search(r"[.!?…:;,]", s):
        return s
    words = [w for w in re.split(r"\s+", s) if w]
    if len(words) < 12:
        return s
    out: list[str] = []
    for i, w in enumerate(words, start=1):
        out.append(w)
        if i < len(words):
            if i % 18 == 0:
                out.append(".")
            elif i % 9 == 0:
                out.append(",")
    s2 = " ".join(out)
    s2 = re.sub(r"\s+([,.])", r"\1", s2)
    return s2.strip()


def _enhance_tts_punctuation_for_pauses(text: str) -> str:
    """Переносы → границы фраз; тире и точка с запятой для пауз."""
    t = (text or "").strip()
    if not t:
        return ""
    t = t.replace("\r\n", "\n").replace("\r", "\n")

    def _close_line(line: str) -> str:
        line = line.strip()
        if not line:
            return line
        line = re.sub(r"\s*[–—]\s*", " — ", line)
        line = re.sub(r";\s*", "; ", line)
        if re.match(r"^-\s+", line):
            inner = re.sub(r"^-\s+", "", line).strip()
            inner = re.sub(r",\s*$", ".", inner)
            if inner and _line_needs_terminal_punct(inner):
                return "- " + inner + "."
            return "- " + inner if inner else line
        if _line_needs_terminal_punct(line):
            return line + "."
        return line

    if "\n" not in t:
        t = re.sub(r"\s*[–—]\s*", " — ", t)
        t = re.sub(r";\s*", "; ", t)
        t = _inject_soft_pauses_without_punctuation(t)
        t = re.sub(r"([.!?])([А-ЯЁA-Z«])", r"\1 \2", t)
        t = re.sub(r"\s{2,}", " ", t).strip()
        t = re.sub(r"\.{2,}", ".", t)
        if t and _line_needs_terminal_punct(t):
            t += "."
        return t

    paras = re.split(r"\n{2,}", t)
    blocks: list[str] = []
    for para in paras:
        lines = [x.strip() for x in para.split("\n") if x.strip()]
        if not lines:
            continue
        blocks.append(" ".join(_close_line(x) for x in lines))
    t = ". ".join(blocks)
    t = re.sub(r"([.!?])\s*([А-ЯЁA-Z«])", r"\1 \2", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    t = re.sub(r"\.{2,}", ".", t)
    if t and _line_needs_terminal_punct(t):
        t += "."
    return t


def _strip_vocalized_punctuation(text: str) -> str:
    """Убирает слова-названия знаков пунктуации, чтобы TTS не озвучивал их (только паузы и интонация)."""
    if not text or not text.strip():
        return (text or "").strip()
    t = (text or "").strip()
    words = [
        r"\bточка\b", r"\bточки\b", r"\bточку\b", r"\bточкой\b",
        r"\bзапятая\b", r"\bзапятые\b", r"\bзапятую\b",
        r"\bдвоеточие\b", r"\bточка с запятой\b",
        r"\bвосклицательный знак\b", r"\bвопросительный знак\b", r"\bтире\b",
        r"\bмноготочие\b", r"\bкавычки\b", r"\bскобки\b", r"\bдефис\b",
    ]
    for w in words:
        t = re.sub(w, " ", t, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", t).strip() or (text or "").strip()


async def _synthesize_edge(content: str, rate: Optional[str]) -> tuple[bytes, str]:
    """Синтез через Edge TTS. Может дать таймаут при недоступности Bing с сервера."""
    try:
        import edge_tts  # type: ignore
    except Exception as e:
        raise TTSProviderError("edge-tts is not installed. Run: pip install edge-tts") from e
    communicate = edge_tts.Communicate(
        text=content,
        voice=MIKHAIL_VOICE_ID,
        rate=_normalize_rate(rate),
    )
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            audio.extend(chunk.get("data") or b"")
    if not audio:
        raise TTSProviderError("No audio generated by Edge TTS")
    return bytes(audio), MIKHAIL_VOICE_ID


async def _synthesize_yandex(content: str) -> tuple[bytes, str]:
    """Синтез через Yandex SpeechKit TTS v1 (работает из РФ, не зависит от Edge/Bing)."""
    settings = get_settings()
    key = (settings.yandex_speechkit_api_key or "").strip()
    if not key:
        raise TTSProviderError("YANDEX_SPEECHKIT_API_KEY не задан для TTS")
    try:
        import httpx
    except ImportError:
        raise TTSProviderError("Для Yandex TTS нужен httpx. pip install httpx") from None
    data = {
        "text": content,
        "lang": "ru-RU",
        "voice": YANDEX_MIKHAIL_VOICE,
        "format": "oggopus",
    }
    headers = {"Authorization": f"Api-Key {key}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(YANDEX_TTS_URL, data=data, headers=headers)
    if resp.status_code != 200:
        logger.warning("Yandex TTS error: %s %s", resp.status_code, resp.text[:500])
        raise TTSProviderError(f"Yandex TTS: {resp.status_code} — {resp.text[:200]}")
    audio = resp.content
    if not audio:
        raise TTSProviderError("Yandex TTS вернул пустой ответ")
    return audio, f"yandex:{YANDEX_MIKHAIL_VOICE}"


async def _synthesize_local(content: str, voice: Optional[str], rate: Optional[str]) -> tuple[bytes, str]:
    """Synthesize speech through local Piper sidecar."""
    settings = get_settings()
    base = (settings.local_tts_url or "").strip().rstrip("/")
    if not base:
        raise TTSProviderError("LOCAL_TTS_URL не задан для TTS_PROVIDER=local")
    voice_id = (voice or settings.local_tts_voice_id or LOCAL_MIKHAIL_VOICE_ID).strip() or LOCAL_MIKHAIL_VOICE_ID
    payload = {
        "text": _soften_for_local_tts(content),
        "voice_id": voice_id,
        "rate": _normalize_local_rate(rate),
    }
    try:
        import httpx
    except ImportError:
        raise TTSProviderError("Для local TTS нужен httpx. pip install httpx") from None
    timeout = max(5.0, float(settings.local_tts_timeout_sec or 25))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{base}/tts/speak", json=payload)
    except Exception as e:
        raise TTSProviderError(f"Local Piper TTS unreachable: {e}") from e
    if resp.status_code != 200:
        detail = (resp.text or "").strip()
        raise TTSProviderError(f"Local Piper TTS: {resp.status_code} — {detail[:240]}")
    audio = resp.content
    if not audio:
        raise TTSProviderError("Local Piper TTS вернул пустой ответ")
    return audio, f"local:{voice_id}"


async def _synthesize_local_xtts(content: str, rate: Optional[str]) -> tuple[bytes, str]:
    """Synthesize speech through local XTTS sidecar."""
    settings = get_settings()
    base = (settings.local_xtts_url or "").strip().rstrip("/")
    if not base:
        raise TTSProviderError("LOCAL_XTTS_URL не задан для TTS_PROVIDER=local_xtts")
    payload = {
        "text": _soften_for_local_tts(content),
        "language": settings.local_xtts_language or "ru",
        "speaker_wav": settings.local_xtts_speaker_wav or "",
        "rate": _normalize_local_rate(rate),
    }
    try:
        import httpx
    except ImportError:
        raise TTSProviderError("Для local XTTS нужен httpx. pip install httpx") from None
    timeout = max(15.0, float(settings.local_xtts_timeout_sec or 90))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{base}/tts/speak", json=payload)
    except Exception as e:
        raise TTSProviderError(f"Local XTTS unreachable: {e}") from e
    if resp.status_code != 200:
        detail = (resp.text or "").strip()
        raise TTSProviderError(f"Local XTTS: {resp.status_code} — {detail[:240]}")
    audio = resp.content
    if not audio:
        raise TTSProviderError("Local XTTS вернул пустой ответ")
    return audio, "local_xtts:mikhail"


async def synthesize_tts(
    text: str,
    voice: Optional[str] = None,
    rate: Optional[str] = None,
) -> tuple[bytes, str, str]:
    """
    Синтез речи (Михаил). Возвращает (audio_bytes, voice_id, provider).
    provider: "edge_tts" | "yandex" | "local_tts" | "local_xtts"; yandex returns oggopus, local returns wav.
    """
    settings = get_settings()
    provider_setting = (settings.tts_provider or "auto").strip().lower() or "auto"
    has_yandex_key = bool((settings.yandex_speechkit_api_key or "").strip())
    has_local_url = bool((settings.local_tts_url or "").strip())
    has_local_xtts_url = bool((settings.local_xtts_url or "").strip())
    source = (text or "").strip()
    if not source:
        raise TTSProviderError("text is required")
    if provider_setting == "local":
        # For Piper, keep punctuation shaping conservative to avoid long pauses.
        content = _strip_vocalized_punctuation(source)
        content = _soften_for_local_tts(content)
    elif provider_setting == "local_xtts":
        content = _strip_vocalized_punctuation(source)
        content = _soften_for_local_tts(content)
    else:
        content = _enhance_tts_punctuation_for_pauses(source)
        content = _strip_vocalized_punctuation(content)
        content = re.sub(r"\s+", " ", content).strip()
    if not content:
        raise TTSProviderError("text is required")

    # Явно только Yandex
    if provider_setting == "yandex":
        if not has_yandex_key:
            raise TTSProviderError("TTS_PROVIDER=yandex задан, но YANDEX_SPEECHKIT_API_KEY не задан")
        audio, voice_id = await _synthesize_yandex(content)
        return audio, voice_id, "yandex"

    if provider_setting == "local":
        if not has_local_url:
            raise TTSProviderError("TTS_PROVIDER=local задан, но LOCAL_TTS_URL не задан")
        audio, voice_id = await _synthesize_local(content, voice=voice, rate=rate)
        return audio, voice_id, "local_tts"

    if provider_setting == "local_xtts":
        if not has_local_xtts_url:
            raise TTSProviderError("TTS_PROVIDER=local_xtts задан, но LOCAL_XTTS_URL не задан")
        audio, voice_id = await _synthesize_local_xtts(content, rate=rate)
        return audio, voice_id, "local_xtts"

    # Только Edge (без fallback)
    if provider_setting == "edge_tts":
        audio, voice_id = await _synthesize_edge(content, rate)
        return audio, voice_id, "edge_tts"

    # auto: сначала Edge с таймаутом, при ошибке — Yandex
    try:
        audio, voice_id = await asyncio.wait_for(
            _synthesize_edge(content, rate),
            timeout=EDGE_TTS_TIMEOUT_SEC,
        )
        return audio, voice_id, "edge_tts"
    except (asyncio.TimeoutError, OSError, Exception) as e:
        logger.warning("Edge TTS failed (will try Yandex): %s", e)
        if has_yandex_key:
            audio, voice_id = await _synthesize_yandex(content)
            return audio, voice_id, "yandex"
        if has_local_url:
            audio, voice_id = await _synthesize_local(content, voice=voice, rate=rate)
            return audio, voice_id, "local_tts"
        if has_local_xtts_url:
            audio, voice_id = await _synthesize_local_xtts(content, rate=rate)
            return audio, voice_id, "local_xtts"
        raise TTSProviderError(
            "Edge TTS недоступен, и fallback-провайдер не настроен. "
            "Задайте YANDEX_SPEECHKIT_API_KEY, LOCAL_TTS_URL или LOCAL_XTTS_URL."
        ) from e
