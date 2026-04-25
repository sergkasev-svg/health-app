"""
Централизованные настройки через pydantic-settings.
Безопасные дефолты для локальной разработки, валидация env.
"""
from __future__ import annotations

import os
from functools import lru_cache
from types import SimpleNamespace
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file() -> Optional[str]:
    for name in (".env", ".env.local", ".env.dev"):
        if os.path.isfile(name):
            return name
    return None


class Settings(BaseSettings):
    """Единый класс настроек. Все переменные окружения с явными именами."""

    model_config = SettingsConfigDict(
        env_file=_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- app ---
    APP_ENV: str = "dev"
    APP_NAME: str = "За Здоровье"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # --- security ---
    SECRET_KEY: str = "dev-secret-change-in-production"
    JWT_SECRET: str = "dev-jwt-secret-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    ADMIN_TOKEN: str = ""
    ALLOWED_ORIGINS: str = "*"

    # --- database ---
    DATABASE_URL: str = ""
    DB_POOL_SIZE: int = 5
    DB_ECHO: bool = False

    # --- storage ---
    FILE_STORAGE_MODE: str = "local"
    FILE_STORAGE_PATH: str = ""
    PRIVATE_MEDIA_PATH: str = ""
    PUBLIC_MEDIA_PATH: str = ""

    # --- queue ---
    QUEUE_MODE: str = "sync"
    REDIS_URL: str = "redis://localhost:6379/0"
    TASK_TIMEOUT_SECONDS: int = 300

    # --- monitoring ---
    SENTRY_DSN: str = ""
    METRICS_ENABLED: bool = False
    OTEL_ENABLED: bool = False
    HEALTHCHECK_ENABLED: bool = True

    # --- product ---
    BILLING_MODE: str = "none"
    ANALYTICS_ENABLED: bool = True
    # --- payments (Stripe) ---
    STRIPE_SECRET_KEY: str = ""
    STRIPE_BASE_URL: str = "https://your-site"
    STRIPE_SUCCESS_URL: str = ""
    STRIPE_CANCEL_URL: str = ""
    STRIPE_PRICE_ID_MONTHLY: str = ""  # price_xxx для месячной подписки
    STRIPE_PRICE_ID_YEARLY: str = ""   # price_xxx для годовой подписки
    STRIPE_WEBHOOK_SECRET: str = ""    # для верификации webhook
    FEATURE_FLAG_ADMIN_DASHBOARD: bool = True
    # Clinical Routing Engine: маршрутизация до гипотез/decision engine (env ENABLE_CLINICAL_ROUTING_ENGINE)
    ENABLE_CLINICAL_ROUTING_ENGINE: bool = False

    # --- docs/reports ---
    PDF_EXPORT_ENABLED: bool = True
    REPORT_EXPORT_QUEUE_ENABLED: bool = False

    @property
    def allowed_origins_list(self) -> List[str]:
        if not self.ALLOWED_ORIGINS or self.ALLOWED_ORIGINS.strip() == "*":
            return ["*"]
        return [x.strip() for x in self.ALLOWED_ORIGINS.split(",") if x.strip()]

    def app_group(self) -> SimpleNamespace:
        return SimpleNamespace(
            env=self.APP_ENV,
            name=self.APP_NAME,
            version=self.APP_VERSION,
            debug=self.DEBUG,
            log_level=self.LOG_LEVEL,
        )

    def security_group(self) -> SimpleNamespace:
        return SimpleNamespace(
            secret_key=self.SECRET_KEY,
            jwt_secret=self.JWT_SECRET,
            access_token_expire_minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES,
            refresh_token_expire_minutes=self.REFRESH_TOKEN_EXPIRE_MINUTES,
            admin_token=self.ADMIN_TOKEN,
            allowed_origins=self.ALLOWED_ORIGINS,
            allowed_origins_list=self.allowed_origins_list,
        )

    def database_group(self) -> SimpleNamespace:
        return SimpleNamespace(
            database_url=self.DATABASE_URL,
            pool_size=self.DB_POOL_SIZE,
            echo=self.DB_ECHO,
        )

    def storage_group(self) -> SimpleNamespace:
        return SimpleNamespace(
            file_storage_mode=self.FILE_STORAGE_MODE,
            file_storage_path=self.FILE_STORAGE_PATH,
            private_media_path=self.PRIVATE_MEDIA_PATH,
            public_media_path=self.PUBLIC_MEDIA_PATH,
        )

    def queue_group(self) -> SimpleNamespace:
        return SimpleNamespace(
            queue_mode=self.QUEUE_MODE,
            redis_url=self.REDIS_URL,
            task_timeout_seconds=self.TASK_TIMEOUT_SECONDS,
        )

    def monitoring_group(self) -> SimpleNamespace:
        return SimpleNamespace(
            sentry_dsn=self.SENTRY_DSN,
            metrics_enabled=self.METRICS_ENABLED,
            otel_enabled=self.OTEL_ENABLED,
            healthcheck_enabled=self.HEALTHCHECK_ENABLED,
        )

    def product_group(self) -> SimpleNamespace:
        return SimpleNamespace(
            billing_mode=self.BILLING_MODE,
            analytics_enabled=self.ANALYTICS_ENABLED,
            feature_flag_admin_dashboard=self.FEATURE_FLAG_ADMIN_DASHBOARD,
        )

    def docs_reports_group(self) -> SimpleNamespace:
        return SimpleNamespace(
            pdf_export_enabled=self.PDF_EXPORT_ENABLED,
            report_export_queue_enabled=self.REPORT_EXPORT_QUEUE_ENABLED,
        )


@lru_cache
def get_settings() -> Settings:
    """Возвращает синглтон настроек. Использовать после загрузки env."""
    return Settings()
