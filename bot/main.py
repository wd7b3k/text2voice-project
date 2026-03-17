import asyncio
import json
import logging
import logging.handlers
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import CallbackQuery, Document, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.database import init_db, AsyncSessionFactory
from db.models import Conversion, ConversionStatus, User
from core.security import encrypt_file, file_hash
from bot.middleware import RateLimitMiddleware, BanCheckMiddleware
from bot.access import check_access, get_limit_message
from workers.tasks import convert_file

BOT_URL       = "https://t.me/t2v_robot"
COMMUNITY_URL = "https://t.me/txt2voice"

# Базовое логирование — только консоль, файл подключается в main()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

TEMP_DIR    = Path(os.getenv("TEMP_DIR", "/app/temp"))
MAX_FILE_MB = int(os.getenv("MAX_FILE_SIZE_MB", 50))
ADMIN_IDS   = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
PROGRESS_NOTIFY_EVERY_SEC = int(os.getenv("PROGRESS_NOTIFY_EVERY_SEC", "20"))

TEMP_DIR.mkdir(parents=True, exist_ok=True)

router = Router()
_progress_throttle: dict[int, datetime] = {}


def _format_eta(eta_seconds: int | None) -> str:
    if eta_seconds is None:
        return "~ неизвестно"
    total = max(0, int(eta_seconds))
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"~ {hours} ч {minutes} мин"
    if minutes:
        return f"~ {minutes} мин {seconds} сек"
    return f"~ {seconds} сек"


def setup_file_logging():
    """Подключаем логирование в файл. Вызывается после старта контейнера."""
    try:
        log_dir = Path(os.getenv("LOG_DIR", "/app/logs"))
        log_dir.mkdir(parents=True, exist_ok=True)

        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

        fh = logging.handlers.RotatingFileHandler(
            log_dir / "bot.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8"
        )
        fh.setFormatter(fmt)

        eh = logging.handlers.RotatingFileHandler(
            log_dir / "errors.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
        )
        eh.setLevel(logging.ERROR)
        eh.setFormatter(fmt)

        root = logging.getLogger()
        root.addHandler(fh)
        root.addHandler(eh)
        logger.info(f"Логирование в файл: {log_dir}")
    except Exception as e:
        logger.warning(f"Не удалось настроить логирование в файл: {e}. Используется только консоль.")


# ── /start ────────────────────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message):
    async with AsyncSessionFactory() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            user = User(
                id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
                language_code=message.from_user.language_code or "ru",
            )
            session.add(user)
            await session.commit()
            logger.info(f"Новый пользователь: {message.from_user.id} @{message.from_user.username}")

    kb = InlineKeyboardBuilder()
    kb.button(text="💬 Сообщество @txt2voice", url=COMMUNITY_URL)
    kb.button(text="💛 Поддержать проект",     url=os.getenv("TRIBUTE_URL", COMMUNITY_URL))
    kb.button(text="❓ Помощь",                callback_data="help")
    kb.adjust(1)

    await message.answer(
        "👋 <b>Text2Voice</b> — конвертирую книги и документы в аудио MP3\n\n"
        "📚 <b>Форматы:</b> PDF · DOCX · DOC · DJVU\n"
        "🎧 <b>Результат:</b> MP3 по главам, название файла сохраняется\n"
        "🔐 <b>Безопасность:</b> файлы шифруются и удаляются через 24 ч\n\n"
        f"Пришлите файл до {MAX_FILE_MB} МБ — начну сразу.\n\n"
        f"📣 Новости: <a href='{COMMUNITY_URL}'>@txt2voice</a>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb.as_markup(),
        disable_web_page_preview=True,
    )


# ── /help ─────────────────────────────────────────────────────────────────
@router.message(Command("help"))
@router.callback_query(F.data == "help")
async def cmd_help(event):
    text = (
        "📖 <b>Как пользоваться Text2Voice</b>\n\n"
        "1. Отправьте файл PDF, DOCX, DOC или DJVU прямо в чат\n"
        "2. Подождите — большие книги обрабатываются несколько минут\n"
        "3. Получите MP3 файлы, разбитые по главам\n\n"
        "📝 <b>Команды:</b>\n"
        "/status  — статус текущей конвертации\n"
        "/history — ваши последние конвертации\n"
        "/donate  — поддержать проект\n"
        "/help    — эта справка\n\n"
        f"💬 Вопросы: <a href='{COMMUNITY_URL}'>@txt2voice</a>"
    )
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        await event.answer()
    else:
        await event.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


# ── /donate ───────────────────────────────────────────────────────────────
@router.message(Command("donate"))
async def cmd_donate(message: Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="💛 Поддержать проект",     url=os.getenv("TRIBUTE_URL", COMMUNITY_URL))
    kb.button(text="💬 Написать в @txt2voice", url=COMMUNITY_URL)
    kb.adjust(1)
    await message.answer(
        "💛 <b>Text2Voice работает бесплатно</b>\n\n"
        "Ваша поддержка помогает оплачивать сервер и развивать проект 🙏\n\n"
        f"📣 Следите за новостями: <a href='{COMMUNITY_URL}'>@txt2voice</a>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb.as_markup(),
        disable_web_page_preview=True,
    )


# ── /status ───────────────────────────────────────────────────────────────
@router.message(Command("status"))
async def cmd_status(message: Message):
    from sqlalchemy import select
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Conversion)
            .where(Conversion.user_id == message.from_user.id)
            .order_by(Conversion.created_at.desc())
            .limit(1)
        )
        conv = result.scalar_one_or_none()

    if not conv:
        await message.answer("У вас пока нет конвертаций. Просто пришлите файл!")
        return

    status_labels = {
        ConversionStatus.PENDING:    "⏳ В очереди",
        ConversionStatus.PROCESSING: "⚙️ Обрабатывается",
        ConversionStatus.DONE:       "✅ Готово",
        ConversionStatus.ERROR:      "❌ Ошибка",
    }
    await message.answer(
        f"📄 <b>{conv.original_filename}</b>\n"
        f"Статус: {status_labels[conv.status]}\n"
        f"Глав: {conv.chapters_count or '—'}",
        parse_mode=ParseMode.HTML,
    )


# ── /history ──────────────────────────────────────────────────────────────
@router.message(Command("history"))
async def cmd_history(message: Message):
    from sqlalchemy import select
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Conversion)
            .where(Conversion.user_id == message.from_user.id)
            .order_by(Conversion.created_at.desc())
            .limit(10)
        )
        convs = result.scalars().all()

    if not convs:
        await message.answer("История пуста.")
        return

    lines = ["📚 <b>Последние конвертации:</b>\n"]
    for c in convs:
        emoji = {"pending": "⏳", "processing": "⚙️", "done": "✅", "error": "❌"}.get(c.status.value, "❓")
        date  = c.created_at.strftime("%d.%m.%Y %H:%M")
        lines.append(f"{emoji} {c.original_filename[:40]} — {date}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


# ── /stats (только для админов) ───────────────────────────────────────────
@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    from sqlalchemy import select, func as sqlfunc
    now   = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week  = now - timedelta(days=7)

    async with AsyncSessionFactory() as session:
        total_users = (await session.execute(
            select(sqlfunc.count(User.id))
        )).scalar() or 0

        new_today = (await session.execute(
            select(sqlfunc.count(User.id)).where(User.created_at >= today)
        )).scalar() or 0

        new_week = (await session.execute(
            select(sqlfunc.count(User.id)).where(User.created_at >= week)
        )).scalar() or 0

        total_conv = (await session.execute(
            select(sqlfunc.count(Conversion.id))
        )).scalar() or 0

        conv_today = (await session.execute(
            select(sqlfunc.count(Conversion.id)).where(Conversion.created_at >= today)
        )).scalar() or 0

        conv_done = (await session.execute(
            select(sqlfunc.count(Conversion.id))
            .where(Conversion.status == ConversionStatus.DONE)
        )).scalar() or 0

        conv_error = (await session.execute(
            select(sqlfunc.count(Conversion.id))
            .where(Conversion.status == ConversionStatus.ERROR)
        )).scalar() or 0

        conv_queue = (await session.execute(
            select(sqlfunc.count(Conversion.id))
            .where(Conversion.status.in_([ConversionStatus.PENDING, ConversionStatus.PROCESSING]))
        )).scalar() or 0

    success_rate = round(conv_done / total_conv * 100) if total_conv > 0 else 0

    await message.answer(
        "📊 <b>Статистика Text2Voice</b>\n\n"
        "<b>👥 Пользователи:</b>\n"
        f"  Всего: {total_users}\n"
        f"  Новых сегодня: {new_today}\n"
        f"  Новых за неделю: {new_week}\n\n"
        "<b>🎧 Конвертации:</b>\n"
        f"  Всего: {total_conv}\n"
        f"  Сегодня: {conv_today}\n"
        f"  Успешных: {conv_done} ({success_rate}%)\n"
        f"  С ошибкой: {conv_error}\n"
        f"  В очереди: {conv_queue}\n\n"
        f"🕐 {now.strftime('%d.%m.%Y %H:%M')} UTC",
        parse_mode=ParseMode.HTML,
    )


# ── /errors (только для админов) ─────────────────────────────────────────
@router.message(Command("errors"))
async def cmd_errors(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    log_dir   = Path(os.getenv("LOG_DIR", "/app/logs"))
    error_log = log_dir / "errors.log"

    if not error_log.exists():
        await message.answer("✅ Ошибок нет.")
        return

    with open(error_log, "r", encoding="utf-8") as f:
        lines = f.readlines()

    last_lines = lines[-30:] if len(lines) > 30 else lines
    if not last_lines:
        await message.answer("✅ Ошибок нет.")
        return

    text = "".join(last_lines)
    if len(text) > 3800:
        text = "...(обрезано)\n" + text[-3800:]

    await message.answer(
        f"🔴 <b>Последние ошибки:</b>\n\n<pre>{text}</pre>",
        parse_mode=ParseMode.HTML,
    )


# ── /admin ────────────────────────────────────────────────────────────────
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer(
        "🔧 <b>Панель администратора</b>\n\n"
        "/stats  — статистика бота\n"
        "/errors — последние ошибки\n\n"
        "<b>Забанить пользователя:</b>\n"
        "<code>docker compose exec postgres psql -U text2voice -d text2voice</code>\n"
        "<code>UPDATE users SET is_banned=true WHERE id=123;</code>",
        parse_mode=ParseMode.HTML,
    )


# ── Обработка файлов ──────────────────────────────────────────────────────
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".djvu"}


@router.message(F.document)
async def handle_document(message: Message, bot: Bot):
    doc = message.document
    ext = Path(doc.file_name or "").suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        await message.answer(
            f"❌ Формат <b>{ext}</b> не поддерживается.\n"
            f"Поддерживаю: PDF · DOCX · DOC · DJVU",
            parse_mode=ParseMode.HTML,
        )
        return

    if doc.file_size and doc.file_size > MAX_FILE_MB * 1024 * 1024:
        size_mb = round(doc.file_size / 1024 / 1024, 1)
        await message.answer(
            f"❌ Файл {size_mb} МБ — слишком большой.\n"
            f"Максимум: <b>{MAX_FILE_MB} МБ</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    async with AsyncSessionFactory() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            await message.answer("Нажмите /start для начала работы")
            return
        allowed, reason = check_access(user)
        if not allowed:
            await message.answer(get_limit_message(reason))
            return

    status_msg = await message.answer("⬇️ Скачиваю файл...")
    logger.info(f"Файл: {doc.file_name} ({round((doc.file_size or 0)/1024/1024, 1)} МБ) от {message.from_user.id}")

    try:
        raw_path = tempfile.mktemp(dir=TEMP_DIR, suffix=ext)
        await bot.download(doc, destination=raw_path)

        with open(raw_path, "rb") as fp:
            content = fp.read()

        fhash = file_hash(content)

        from sqlalchemy import select
        from db.models import CachedFile
        async with AsyncSessionFactory() as session:
            cached = (await session.execute(
                select(CachedFile).where(CachedFile.file_hash == fhash)
            )).scalar_one_or_none()

        if cached:
            await status_msg.edit_text("📦 Файл уже конвертировался — отправляю из кэша...")
            await _send_from_cache(message, bot, json.loads(cached.mp3_paths))
            Path(raw_path).unlink(missing_ok=True)
            return

        enc_path = encrypt_file(raw_path)

        async with AsyncSessionFactory() as session:
            conv = Conversion(
                user_id=message.from_user.id,
                original_filename=doc.file_name or f"file{ext}",
                file_hash=fhash,
                file_size_bytes=doc.file_size or 0,
                status=ConversionStatus.PENDING,
            )
            session.add(conv)
            await session.commit()
            await session.refresh(conv)
            conv_id = conv.id

        task = convert_file.delay(
            conversion_id=conv_id,
            user_id=message.from_user.id,
            enc_file_path=enc_path,
            original_filename=doc.file_name or f"file{ext}",
        )

        async with AsyncSessionFactory() as session:
            c = await session.get(Conversion, conv_id)
            c.celery_task_id = task.id
            await session.commit()

        await status_msg.edit_text(
            f"✅ <b>Принято в обработку!</b>\n\n"
            f"📄 {doc.file_name}\n"
            f"⏱ Оценка времени: <b>{_format_eta(_estimate_initial_eta(doc.file_size or 0))}</b>\n"
            f"🔄 Буду присылать этапы обработки.\n"
            f"⏳ Конвертирую по главам — пришлю когда готово.\n\n"
            f"Статус: /status",
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        logger.error(f"Ошибка обработки файла от {message.from_user.id}: {e}", exc_info=True)
        await status_msg.edit_text(
            "❌ Ошибка при обработке файла.\n"
            f"Напишите нам: <a href='{COMMUNITY_URL}'>@txt2voice</a>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def _send_from_cache(message: Message, bot: Bot, paths: list):
    for item in paths:
        from core.security import decrypt_file
        dec_path = tempfile.mktemp(suffix=".mp3")
        try:
            decrypt_file(item["path"], dec_path)
            with open(dec_path, "rb") as f:
                await message.answer_audio(audio=f, title=item["title"], performer="Text2Voice")
        except Exception as e:
            logger.error(f"Ошибка отправки кэша: {e}", exc_info=True)
        finally:
            Path(dec_path).unlink(missing_ok=True)


# ── Redis listener ────────────────────────────────────────────────────────
async def redis_listener(bot: Bot):
    import redis.asyncio as aioredis
    r = aioredis.from_url(os.getenv("REDIS_URL"))
    pubsub = r.pubsub()
    await pubsub.subscribe("conversions")
    logger.info("Redis listener запущен")

    async for msg in pubsub.listen():
        if msg["type"] != "message":
            continue
        try:
            data    = json.loads(msg["data"])
            user_id = data["user_id"]

            if data["event"] == "done":
                paths = data["paths"]
                await bot.send_message(
                    user_id,
                    f"🎧 <b>Готово!</b> Отправляю {len(paths)} аудиофайл(ов)...",
                    parse_mode=ParseMode.HTML,
                )
                for item in paths:
                    from core.security import decrypt_file
                    dec_path = tempfile.mktemp(suffix=".mp3")
                    try:
                        decrypt_file(item["path"], dec_path)
                        with open(dec_path, "rb") as f:
                            await bot.send_audio(
                                chat_id=user_id, audio=f,
                                title=item["title"], performer="Text2Voice"
                            )
                    except Exception as e:
                        logger.error(f"Ошибка отправки аудио: {e}", exc_info=True)
                    finally:
                        Path(dec_path).unlink(missing_ok=True)

            elif data["event"] == "progress":
                conv_id = int(data.get("conversion_id", 0))
                now = datetime.utcnow()
                prev = _progress_throttle.get(conv_id)
                stage = data.get("stage", "")

                if prev and stage not in {"queued", "chapters", "finalize", "chapter_done"}:
                    if (now - prev).total_seconds() < PROGRESS_NOTIFY_EVERY_SEC:
                        continue

                _progress_throttle[conv_id] = now

                eta_text = _format_eta(data.get("eta_seconds"))
                progress_value = data.get("progress")
                progress_text = f"{progress_value}%" if progress_value is not None else "—"
                await bot.send_message(
                    user_id,
                    "🔄 <b>Конвертация в процессе</b>\n"
                    f"{data.get('message', 'Обработка продолжается…')}\n"
                    f"Прогресс: <b>{progress_text}</b>\n"
                    f"Осталось: <b>{eta_text}</b>",
                    parse_mode=ParseMode.HTML,
                )

            elif data["event"] == "error":
                await bot.send_message(
                    user_id,
                    f"❌ Ошибка конвертации.\n{data.get('error', '')}\n\n"
                    f"Напишите нам: <a href='{COMMUNITY_URL}'>@txt2voice</a>",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
        except Exception as e:
            logger.error(f"Redis listener error: {e}", exc_info=True)


def _estimate_initial_eta(file_size_bytes: int) -> int:
    # Грубая оценка до анализа текста: базовое время + время пропорционально размеру.
    base = int(os.getenv("INITIAL_ETA_BASE_SECONDS", "420"))
    per_mb = int(os.getenv("INITIAL_ETA_PER_MB_SECONDS", "55"))
    size_mb = max(1, round(file_size_bytes / (1024 * 1024)))
    return base + size_mb * per_mb


# ── Запуск ────────────────────────────────────────────────────────────────
async def main():
    # Логирование в файл — после монтирования volumes
    setup_file_logging()

    await init_db()

    from aiogram.client.default import DefaultBotProperties
    bot     = Bot(token=os.getenv("BOT_TOKEN"), default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    storage = RedisStorage.from_url(os.getenv("REDIS_URL"))
    dp      = Dispatcher(storage=storage)

    dp.message.middleware(BanCheckMiddleware())
    dp.message.middleware(RateLimitMiddleware())
    dp.include_router(router)

    asyncio.create_task(redis_listener(bot))

    me = await bot.get_me()
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info(f"  Бот запущен: @{me.username}")
    logger.info(f"  Макс. файл : {MAX_FILE_MB} МБ")
    logger.info(f"  Админы     : {ADMIN_IDS}")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
