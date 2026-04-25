"""Database connection (SQLAlchemy)."""
import logging

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Если DATABASE_URL не задан, используем SQLite для dev
database_url = settings.DATABASE_URL or "sqlite:///./health_app.db"

engine = create_engine(
    database_url,
    connect_args={"check_same_thread": False} if "sqlite" in database_url else {},
    echo=settings.DB_ECHO,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def ensure_users_auth_subject_column() -> None:
    """Добавить колонку users.auth_subject в существующих БД (SQLite/Postgres), без Alembic."""
    from sqlalchemy import text

    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN auth_subject VARCHAR(128)"))
    except Exception:
        pass
    try:
        with engine.begin() as conn:
            conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_auth_subject ON users(auth_subject)")
            )
    except Exception:
        pass


def ensure_database_schema() -> None:
    """
    Создать отсутствующие таблицы (report_history, followup_reminders, marker_snapshots и т.д.).
    Без этого GET /api/memory/* даёт 500: «no such table: report_history».
    """
    import importlib

    importlib.import_module("app.models")  # регистрация всех таблиц на Base.metadata
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        logger.warning("create_all failed: %s", e)
    try:
        ensure_users_auth_subject_column()
    except Exception as e:
        logger.warning("ensure_users_auth_subject_column failed: %s", e)


def get_db():
    """Dependency для FastAPI: получение DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# В `app.main` uvicorn смонтирован на ASGI-диспетчер `_dispatch`, из‑за чего lifespan
# внутреннего FastAPI может не вызываться — схему БД поднимаем при импорте модуля.
try:
    ensure_database_schema()
except Exception as e:
    logger.warning("ensure_database_schema failed: %s", e)
