"""
bot/middleware.py — middleware для rate limit и бана
"""

import os
from typing import Any, Awaitable, Callable

import redis.asyncio as aioredis
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(os.getenv("REDIS_URL"))
    return _redis


# Лимиты запросов для каждого уровня доступа (запросов в минуту)
RATE_LIMITS = {
    "free":       5,
    "donor":      15,
    "basic":      30,
    "pro":        60,
    "enterprise": 200,
}


class RateLimitMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if not hasattr(event, "from_user") or not event.from_user:
            return await handler(event, data)

        user_id = event.from_user.id
        r = get_redis()

        # Получаем уровень из кэша (чтобы не дёргать БД на каждое сообщение)
        level_key = f"user_level:{user_id}"
        level = (await r.get(level_key) or b"free").decode()
        limit = RATE_LIMITS.get(level, 5)

        rate_key = f"rate:{user_id}"
        count = await r.incr(rate_key)
        if count == 1:
            await r.expire(rate_key, 60)

        if count > limit:
            await event.answer(
                f"⏳ Слишком много запросов. Лимит: {limit}/мин. Попробуйте через минуту."
            )
            return

        return await handler(event, data)


class BanCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if not hasattr(event, "from_user") or not event.from_user:
            return await handler(event, data)

        user_id = event.from_user.id
        r = get_redis()

        # Бан кэшируется в Redis, чтобы не делать запрос к БД на каждое сообщение
        ban_key = f"banned:{user_id}"
        is_banned = await r.get(ban_key)

        if is_banned is None:
            # Первый раз — проверяем БД и кэшируем на 5 минут
            from db.database import AsyncSessionFactory
            from db.models import User
            async with AsyncSessionFactory() as session:
                user = await session.get(User, user_id)
                if user and user.is_banned:
                    await r.setex(ban_key, 300, "1")
                    await event.answer("🚫 Ваш аккаунт заблокирован.")
                    return
                else:
                    await r.setex(ban_key, 300, "0")
        elif is_banned == b"1":
            await event.answer("🚫 Ваш аккаунт заблокирован.")
            return

        return await handler(event, data)
