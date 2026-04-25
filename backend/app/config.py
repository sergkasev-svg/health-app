"""App configuration (env, API keys, DB, object storage, LLM worker)."""
import os
from typing import Optional


class Settings:
    def __init__(self) -> None:
        # LLM: when set, app calls worker instead of OpenAI directly (worker holds OPENAI_*)
        self.llm_worker_url: str = (os.getenv("LLM_WORKER_URL") or "").strip().rstrip("/")
        # Fallback: direct OpenAI from app (e.g. dev or single-container)
        self.openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
        # Для медицинского диалога по умолчанию используем более устойчивую модель,
        # чтобы снизить поверхностные/нерелевантные ответы (можно переопределить env-переменной).
        self.openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o")
        # STT: openai | yandex | auto
        # auto: если есть Yandex credentials, используем Yandex как приоритетный серверный STT.
        # Поддерживаем оба варианта авторизации Yandex: API Key и IAM token.
        self.stt_provider: str = (os.getenv("STT_PROVIDER") or "yandex").strip().lower() or "yandex"
        self.yandex_speechkit_api_key: str = (
            os.getenv("YANDEX_SPEECHKIT_API_KEY")
            or os.getenv("YANDEX_API_KEY")
            or os.getenv("YC_API_KEY")
            or ""
        ).strip()
        self.yandex_speechkit_iam_token: str = (
            os.getenv("YANDEX_IAM_TOKEN")
            or os.getenv("YC_IAM_TOKEN")
            or os.getenv("IAM_TOKEN")
            or ""
        ).strip()
        # TTS: edge_tts | yandex | local | local_xtts | auto
        # Для RU-first стека по умолчанию — yandex (стабильная озвучка и предсказуемый пайплайн).
        self.tts_provider: str = (os.getenv("TTS_PROVIDER") or "yandex").strip().lower() or "yandex"
        # Local offline TTS (Piper sidecar)
        self.local_tts_url: str = (os.getenv("LOCAL_TTS_URL") or "http://local-tts:8090").strip().rstrip("/")
        self.local_tts_timeout_sec: float = float(os.getenv("LOCAL_TTS_TIMEOUT_SEC") or "25")
        self.local_tts_voice_id: str = (os.getenv("LOCAL_TTS_VOICE_ID") or "ru_RU-ruslan-medium").strip()
        # Local high-quality XTTS sidecar (voice cloning)
        self.local_xtts_url: str = (os.getenv("LOCAL_XTTS_URL") or "http://local-xtts:8091").strip().rstrip("/")
        self.local_xtts_timeout_sec: float = float(os.getenv("LOCAL_XTTS_TIMEOUT_SEC") or "90")
        self.local_xtts_language: str = (os.getenv("LOCAL_XTTS_LANGUAGE") or "ru").strip().lower() or "ru"
        self.local_xtts_speaker_wav: str = (os.getenv("LOCAL_XTTS_SPEAKER_WAV") or "/voices/mikhail_reference.wav").strip()
        # Database and object storage (production)
        self.database_url: str = os.getenv("DATABASE_URL", "")
        self.object_storage_bucket: str = os.getenv("OBJECT_STORAGE_BUCKET", "")
        self.object_storage_endpoint: str = os.getenv("OBJECT_STORAGE_ENDPOINT", "")
        self.object_storage_region: str = os.getenv("OBJECT_STORAGE_REGION", "auto")
        self.object_storage_access_key: str = os.getenv("OBJECT_STORAGE_ACCESS_KEY", "")
        self.object_storage_secret_key: str = os.getenv("OBJECT_STORAGE_SECRET_KEY", "")
        # Личный кабинет: мастер-пароль для входа на уровень администратора (один на всё приложение).
        self.admin_master_password: str = (os.getenv("ADMIN_MASTER_PASSWORD") or "").strip()
        # Non-medical web search fallback (без UI переключателя; включается env-переменной).
        self.non_medical_web_search_enabled: bool = (os.getenv("NON_MEDICAL_WEB_SEARCH_ENABLED") or "0").strip().lower() in {
            "1", "true", "yes", "on"
        }
        self.non_medical_web_search_timeout_sec: float = float(
            os.getenv("NON_MEDICAL_WEB_SEARCH_TIMEOUT_SEC") or "3.5"
        )
        whitelist_raw = (
            os.getenv("NON_MEDICAL_WEB_SEARCH_WHITELIST")
            or "погода,стол,компьютер,ноутбук,монитор,клавиатура,мышь,бюджет,цена,стоимость,купить,выбрать,фильм,музыка,игра"
        )
        self.non_medical_web_search_whitelist: list[str] = [
            x.strip().lower() for x in whitelist_raw.split(",") if x.strip()
        ]
        # Online medical retrieval (RAG-like hints for trusted public sources).
        self.online_medical_rag_enabled: bool = (os.getenv("ONLINE_MEDICAL_RAG_ENABLED") or "0").strip().lower() in {
            "1", "true", "yes", "on"
        }
        self.online_medical_pubmed_enabled: bool = (os.getenv("ONLINE_MEDICAL_PUBMED_ENABLED") or "0").strip().lower() in {
            "1", "true", "yes", "on"
        }
        self.online_medical_timeout_sec: float = float(os.getenv("ONLINE_MEDICAL_TIMEOUT_SEC") or "3.0")
        self.online_medical_max_sources: int = max(1, min(5, int(os.getenv("ONLINE_MEDICAL_MAX_SOURCES") or "3")))
        allowed_domains_raw = (
            os.getenv("ONLINE_MEDICAL_ALLOWED_DOMAINS")
            or "clinical,research,endocrine,cardio,gastro,respiratory,neuro,nutrition,drugs,activity"
        )
        self.online_medical_allowed_domains: set[str] = {
            x.strip().lower() for x in allowed_domains_raw.split(",") if x.strip()
        }


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
