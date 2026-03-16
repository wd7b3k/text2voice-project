"""
db/models.py — модели базы данных
SQLAlchemy 2.0 async, PostgreSQL
"""

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, ForeignKey,
    Integer, String, Text, func
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AccessLevel(str, PyEnum):
    FREE         = "free"
    DONOR        = "donor"
    BASIC        = "basic"       # будущая платная подписка
    PRO          = "pro"         # будущая премиум подписка
    ENTERPRISE   = "enterprise"  # будущий B2B


class ConversionStatus(str, PyEnum):
    PENDING    = "pending"
    PROCESSING = "processing"
    DONE       = "done"
    ERROR      = "error"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int]              = mapped_column(BigInteger, primary_key=True)  # Telegram ID
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str | None]= mapped_column(String(128))
    language_code: Mapped[str]   = mapped_column(String(8), default="ru")

    access_level: Mapped[AccessLevel] = mapped_column(
        Enum(AccessLevel), default=AccessLevel.FREE, index=True
    )
    files_this_month: Mapped[int] = mapped_column(Integer, default=0)
    total_files: Mapped[int]      = mapped_column(Integer, default=0)

    is_banned: Mapped[bool]       = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool]        = mapped_column(Boolean, default=False)

    last_donation_at: Mapped[datetime | None] = mapped_column(DateTime)
    plan_expires_at:  Mapped[datetime | None] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    conversions: Mapped[list["Conversion"]] = relationship(
        back_populates="user", lazy="selectin"
    )


class Conversion(Base):
    __tablename__ = "conversions"

    id: Mapped[int]          = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int]     = mapped_column(ForeignKey("users.id"), index=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(64))

    original_filename: Mapped[str]  = mapped_column(String(256))
    file_hash: Mapped[str]          = mapped_column(String(64), index=True)
    file_size_bytes: Mapped[int]    = mapped_column(BigInteger, default=0)

    status: Mapped[ConversionStatus] = mapped_column(
        Enum(ConversionStatus), default=ConversionStatus.PENDING, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text)

    chapters_count: Mapped[int]   = mapped_column(Integer, default=0)
    output_paths: Mapped[str | None] = mapped_column(Text)  # JSON список путей

    created_at: Mapped[datetime]  = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped["User"] = relationship(back_populates="conversions")


class CachedFile(Base):
    __tablename__ = "cached_files"

    id: Mapped[int]       = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_hash: Mapped[str]= mapped_column(String(64), unique=True, index=True)
    mp3_paths: Mapped[str]= mapped_column(Text)   # JSON список путей
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    hit_count: Mapped[int]= mapped_column(Integer, default=0)
