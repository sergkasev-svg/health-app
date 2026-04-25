"""
Транскрипция голоса в текст: OpenAI Whisper API и/или Yandex SpeechKit.
Используется для надёжной записи жалоб без ограничений браузерного Web Speech API.
При 403 (регион OpenAI) можно использовать Yandex SpeechKit (STT_PROVIDER=yandex или auto).
"""
import asyncio
import io
import logging
import shutil
import subprocess
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

YANDEX_STT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"


def _ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg"))


def _has_yandex_credentials() -> bool:
    settings = get_settings()
    api_key = (settings.yandex_speechkit_api_key or "").strip()
    iam_token = (getattr(settings, "yandex_speechkit_iam_token", "") or "").strip()
    return bool(api_key or iam_token)


def get_stt_runtime_status() -> dict:
    """
    Технический статус server-side STT без секретов.
    Нужен фронту, чтобы показать оператору, почему транскрипция может не работать.
    """
    settings = get_settings()
    provider = (settings.stt_provider or "auto").strip().lower() or "auto"
    has_openai = bool((settings.openai_api_key or "").strip())
    has_yandex = _has_yandex_credentials()
    has_ffmpeg = _ffmpeg_available()
    yandex_ready = has_yandex and has_ffmpeg
    openai_ready = has_openai
    if provider == "yandex":
        active = "yandex" if yandex_ready else ("openai" if openai_ready else "yandex")
    elif provider == "openai":
        active = "openai" if openai_ready else ("yandex" if yandex_ready else "openai")
    else:
        active = "yandex" if yandex_ready else ("openai" if openai_ready else "yandex")

    server_ready = False
    notes: list[str] = []
    if not has_yandex:
        notes.append("Не задан Yandex ключ или IAM token.")
    if not has_ffmpeg:
        notes.append("Не найден ffmpeg в PATH.")
    if not has_openai:
        notes.append("Не задан OPENAI_API_KEY.")
    server_ready = yandex_ready or openai_ready

    return {
        "provider_config": provider,
        "active_provider": active,
        "server_ready": server_ready,
        "has_yandex_credentials": has_yandex,
        "has_openai_key": has_openai,
        "ffmpeg_available": has_ffmpeg,
        "notes": notes,
    }


def _webm_to_oggopus(audio_bytes: bytes) -> bytes:
    """Конвертирует webm (opus) в ogg/opus для Yandex SpeechKit. Требует ffmpeg."""
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", "pipe:0",
                "-acodec", "libopus",
                "-f", "ogg",
                "-ac", "1",
                "-ar", "16000",
                "pipe:1",
            ],
            input=audio_bytes,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            logger.warning("ffmpeg webm->oggopus failed: %s", proc.stderr[:500] if proc.stderr else "no stderr")
            raise RuntimeError("Конвертация аудио не удалась (ffmpeg)")
        return proc.stdout
    except FileNotFoundError:
        raise RuntimeError("Для Yandex STT нужен ffmpeg. Установите: apt-get install ffmpeg") from None


async def _transcribe_openai(audio_bytes: bytes, content_type: Optional[str] = None) -> str:
    """Транскрипция через OpenAI Whisper. Может выбросить PermissionDeniedError при 403."""
    settings = get_settings()
    if not (settings.openai_api_key or "").strip():
        raise RuntimeError("OPENAI_API_KEY не задан. Транскрипция недоступна.")
    try:
        from openai import AsyncOpenAI
    except ImportError:
        raise RuntimeError("openai не установлен. pip install openai")
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    ext = "webm"
    if content_type:
        if "webm" in content_type:
            ext = "webm"
        elif "mp3" in content_type or "mpeg" in content_type:
            ext = "mp3"
        elif "wav" in content_type:
            ext = "wav"
        elif "m4a" in content_type or "mp4" in content_type:
            ext = "m4a"
    file_like = io.BytesIO(audio_bytes)
    file_like.name = f"audio.{ext}"
    transcript = await client.audio.transcriptions.create(
        model="whisper-1",
        file=file_like,
        language="ru",
        response_format="text",
    )
    text = (transcript if isinstance(transcript, str) else getattr(transcript, "text", "")) or ""
    return text.strip()


def _transcribe_yandex_sync(audio_bytes: bytes, content_type: Optional[str] = None) -> str:
    """Синхронная транскрипция через Yandex SpeechKit v1 (REST). Принимает webm — конвертирует в oggopus."""
    settings = get_settings()
    api_key = settings.yandex_speechkit_api_key
    iam_token = getattr(settings, "yandex_speechkit_iam_token", "") or ""
    if not api_key and not iam_token:
        raise RuntimeError(
            "Yandex STT не настроен: задайте YANDEX_SPEECHKIT_API_KEY (или YANDEX_API_KEY/YC_API_KEY) "
            "или YANDEX_IAM_TOKEN (или YC_IAM_TOKEN)."
        )
    # Yandex v1 принимает только oggopus или lpcm; браузер присылает webm (или без content-type)
    ct = (content_type or "").lower()
    if "webm" in ct or not content_type or "octet-stream" in ct:
        audio_bytes = _webm_to_oggopus(audio_bytes)
    import httpx
    params = {"lang": "ru-RU", "format": "oggopus", "topic": "general"}
    headers = {"Authorization": f"Api-Key {api_key}"} if api_key else {"Authorization": f"Bearer {iam_token}"}
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(YANDEX_STT_URL, params=params, content=audio_bytes, headers=headers)
    if resp.status_code != 200:
        logger.warning("Yandex STT error: %s %s", resp.status_code, resp.text[:500])
        raise RuntimeError(f"Yandex SpeechKit: {resp.status_code} — {resp.text[:200]}")
    data = resp.json()
    text = (data.get("result") or "").strip()
    return text


async def transcribe_audio(audio_bytes: bytes, content_type: Optional[str] = None) -> str:
    """
    Транскрибирует аудио в текст. Язык — русский.
    Поддерживаются форматы: webm, mp3, wav, m4a (для OpenAI); для Yandex webm конвертируется в oggopus через ffmpeg.
    Выбор провайдера: STT_PROVIDER=openai | yandex | auto.
    По умолчанию в проекте: yandex.
    Каскад деградации: Yandex -> OpenAI -> browser STT (последний реализован на фронтенде).
    """
    settings = get_settings()
    provider = (settings.stt_provider or "auto").strip().lower() or "auto"
    has_yandex = bool((settings.yandex_speechkit_api_key or "").strip() or (getattr(settings, "yandex_speechkit_iam_token", "") or "").strip())

    if provider == "yandex":
        try:
            return await asyncio.to_thread(_transcribe_yandex_sync, audio_bytes, content_type)
        except Exception as e:
            if (settings.openai_api_key or "").strip():
                logger.info("Yandex STT failed in yandex mode (%s), falling back to OpenAI", type(e).__name__)
                return await _transcribe_openai(audio_bytes, content_type)
            raise RuntimeError(f"Ошибка транскрипции: {e}") from e

    if provider == "openai":
        try:
            return await _transcribe_openai(audio_bytes, content_type)
        except Exception as e:
            if has_yandex:
                logger.info("OpenAI STT failed in openai mode (%s), falling back to Yandex", type(e).__name__)
                return await asyncio.to_thread(_transcribe_yandex_sync, audio_bytes, content_type)
            raise

    # auto: для RU-сценариев приоритетно пробуем Yandex (если настроен), иначе OpenAI.
    if has_yandex:
        try:
            return await asyncio.to_thread(_transcribe_yandex_sync, audio_bytes, content_type)
        except Exception as e:
            logger.warning("Yandex STT failed in auto mode: %s", e)
            # Если OpenAI тоже не настроен, отдаём исходную ошибку по Yandex (она наиболее полезна).
            if not (settings.openai_api_key or "").strip():
                raise RuntimeError(f"Ошибка транскрипции: {e}") from e
    try:
        return await _transcribe_openai(audio_bytes, content_type)
    except Exception as e:
        try:
            from openai import PermissionDeniedError
            is_permission = isinstance(e, PermissionDeniedError)
        except ImportError:
            is_permission = "PermissionDenied" in type(e).__name__ or "403" in str(e)
        e_text = str(e)
        low = e_text.lower()
        is_403 = getattr(e, "status_code", None) == 403 or "403" in e_text or "unsupported_country" in low
        missing_openai_key = "openai_api_key" in low and ("не задан" in low or "not set" in low)
        transient_openai = any(k in low for k in ("timeout", "timed out", "503", "service unavailable", "temporarily unavailable"))
        if has_yandex and (is_403 or is_permission or missing_openai_key or transient_openai):
            logger.info("OpenAI STT unavailable (%s), falling back to Yandex SpeechKit", type(e).__name__)
            return await asyncio.to_thread(_transcribe_yandex_sync, audio_bytes, content_type)
        logger.exception("Whisper transcribe failed")
        raise RuntimeError(f"Ошибка транскрипции: {e}") from e
