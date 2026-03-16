"""
workers/tasks.py — Celery задачи конвертации
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from celery import Celery
from celery.utils.log import get_task_logger

# Импортируем после инициализации окружения
from core.chapters import split_into_chapters
from core.extractor import extract_text
from core.security import decrypt_file, encrypt_file, file_hash, make_mp3_filename
from core.tts import get_tts_engine

logger = get_task_logger(__name__)

celery_app = Celery(
    "text2voice",
    broker=os.getenv("REDIS_URL"),
    backend=os.getenv("REDIS_URL"),
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Moscow",
    task_track_started=True,
    task_acks_late=True,                # подтверждение только после выполнения
    worker_prefetch_multiplier=1,       # не брать следующую задачу пока не сделана текущая
    task_soft_time_limit=1800,          # 30 минут лимит на задачу
    task_time_limit=2100,               # 35 минут жёсткий лимит
)

# Периодические задачи (Celery Beat)
celery_app.conf.beat_schedule = {
    "cleanup-expired-files": {
        "task": "workers.tasks.cleanup_expired_files",
        "schedule": 3600.0,  # каждый час
    },
    "reset-monthly-counters": {
        "task": "workers.tasks.reset_monthly_counters",
        "schedule": 86400.0,  # каждый день
    },
}

TEMP_DIR   = Path(os.getenv("TEMP_DIR", "/app/temp"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/app/output"))

TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="workers.tasks.convert_file",
)
def convert_file(
    self,
    conversion_id: int,
    user_id: int,
    enc_file_path: str,
    original_filename: str,
):
    """
    Основная задача конвертации.
    1. Расшифровать входной файл
    2. Извлечь текст
    3. Разбить на главы
    4. Синтезировать речь для каждой главы
    5. Зашифровать результаты
    6. Уведомить бот через Redis pub/sub
    """
    from db.sync_ops import update_conversion_status, save_output_paths  # sync ORM для Celery

    logger.info(f"[Task {self.request.id}] Начинаем конвертацию {original_filename}")

    # Обновляем статус в БД
    update_conversion_status(conversion_id, "processing")

    try:
        # 1. Расшифровываем входной файл
        ext = Path(original_filename).suffix.lower()
        decrypted_input = TEMP_DIR / f"{self.request.id}_input{ext}"
        decrypt_file(enc_file_path, str(decrypted_input))

        # 2. Извлекаем текст
        logger.info("Извлекаем текст...")
        text = extract_text(str(decrypted_input))
        decrypted_input.unlink(missing_ok=True)

        if not text or len(text.strip()) < 50:
            raise ValueError("Не удалось извлечь текст из файла")

        # 3. Разбиваем на главы
        chapters = split_into_chapters(text)
        logger.info(f"Найдено глав: {len(chapters)}")

        # 4. Синтезируем речь
        tts = get_tts_engine()
        output_paths = []

        for chapter in chapters:
            mp3_name = make_mp3_filename(original_filename, chapter.index, chapter.title)
            mp3_path = OUTPUT_DIR / mp3_name
            enc_mp3_path = str(mp3_path) + ".enc"

            logger.info(f"  Синтез главы {chapter.index}/{len(chapters)}: {chapter.title}")
            tts.synthesize(chapter.content, str(mp3_path))

            # Шифруем готовый mp3
            encrypt_file(str(mp3_path))
            output_paths.append({
                "index": chapter.index,
                "title": chapter.title,
                "path": enc_mp3_path,
                "expires_at": (
                    datetime.utcnow() + timedelta(hours=int(os.getenv("FILE_TTL_HOURS", 24)))
                ).isoformat(),
            })

        # 5. Сохраняем пути в БД
        save_output_paths(conversion_id, output_paths, len(chapters))

        # 6. Уведомляем бот через Redis
        _notify_bot(user_id, conversion_id, output_paths)

        logger.info(f"[Task {self.request.id}] Готово! {len(chapters)} глав(ы)")
        return {"status": "done", "chapters": len(chapters)}

    except Exception as exc:
        logger.error(f"[Task {self.request.id}] Ошибка: {exc}", exc_info=True)
        update_conversion_status(conversion_id, "error", str(exc))
        _notify_bot_error(user_id, conversion_id, str(exc))
        raise self.retry(exc=exc)


@celery_app.task(name="workers.tasks.cleanup_expired_files")
def cleanup_expired_files():
    """Удаляет просроченные файлы. Запускается Celery Beat каждый час."""
    from db.sync_ops import get_expired_conversions, mark_files_deleted
    import os

    expired = get_expired_conversions()
    deleted = 0
    for conv in expired:
        if conv.output_paths:
            paths = json.loads(conv.output_paths)
            for item in paths:
                try:
                    os.unlink(item["path"])
                    deleted += 1
                except FileNotFoundError:
                    pass
        mark_files_deleted(conv.id)

    logger.info(f"Очистка: удалено {deleted} файлов")


@celery_app.task(name="workers.tasks.reset_monthly_counters")
def reset_monthly_counters():
    """Сбрасывает счётчики files_this_month в начале месяца."""
    from db.sync_ops import reset_all_monthly_counters
    from datetime import datetime
    if datetime.utcnow().day == 1:
        reset_all_monthly_counters()
        logger.info("Счётчики за месяц сброшены")


def _notify_bot(user_id: int, conversion_id: int, output_paths: list):
    """Публикует событие в Redis, бот его подхватывает и отправляет файлы."""
    import redis, json
    r = redis.from_url(os.getenv("REDIS_URL"))
    r.publish("conversions", json.dumps({
        "event": "done",
        "user_id": user_id,
        "conversion_id": conversion_id,
        "paths": output_paths,
    }))


def _notify_bot_error(user_id: int, conversion_id: int, error: str):
    import redis, json
    r = redis.from_url(os.getenv("REDIS_URL"))
    r.publish("conversions", json.dumps({
        "event": "error",
        "user_id": user_id,
        "conversion_id": conversion_id,
        "error": error,
    }))
