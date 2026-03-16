"""
db/sync_ops.py — синхронные операции с БД для Celery воркеров
(Celery не поддерживает async, используем sync SQLAlchemy)
"""

import json
import os
from datetime import datetime, timedelta

from sqlalchemy import create_engine, update, select
from sqlalchemy.orm import Session, sessionmaker

from db.models import Conversion, ConversionStatus, User

# Синхронный движок для Celery
_sync_engine = create_engine(
    os.getenv("DATABASE_URL", "").replace("+asyncpg", "+psycopg2"),
    pool_size=5,
    max_overflow=10,
)
SyncSession = sessionmaker(bind=_sync_engine)


def update_conversion_status(
    conversion_id: int,
    status: str,
    error_message: str | None = None,
):
    with SyncSession() as session:
        conv = session.get(Conversion, conversion_id)
        if conv:
            conv.status = ConversionStatus(status)
            if error_message:
                conv.error_message = error_message
            if status == "done":
                conv.completed_at = datetime.utcnow()
            session.commit()


def save_output_paths(conversion_id: int, paths: list, chapters_count: int):
    with SyncSession() as session:
        conv = session.get(Conversion, conversion_id)
        if conv:
            conv.output_paths = json.dumps(paths, ensure_ascii=False)
            conv.chapters_count = chapters_count
            conv.status = ConversionStatus.DONE
            conv.completed_at = datetime.utcnow()
            # Увеличиваем счётчики пользователя
            user = session.get(User, conv.user_id)
            if user:
                user.total_files += 1
                user.files_this_month += 1
            session.commit()


def get_expired_conversions() -> list[Conversion]:
    ttl_hours = int(os.getenv("FILE_TTL_HOURS", 24))
    expiry = datetime.utcnow() - timedelta(hours=ttl_hours)
    with SyncSession() as session:
        result = session.execute(
            select(Conversion)
            .where(Conversion.status == ConversionStatus.DONE)
            .where(Conversion.completed_at < expiry)
            .where(Conversion.output_paths.isnot(None))
        )
        return list(result.scalars().all())


def mark_files_deleted(conversion_id: int):
    with SyncSession() as session:
        conv = session.get(Conversion, conversion_id)
        if conv:
            conv.output_paths = None
            session.commit()


def reset_all_monthly_counters():
    with SyncSession() as session:
        session.execute(update(User).values(files_this_month=0))
        session.commit()
