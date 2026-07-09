"""Общие фикстуры для тестов.

Integration-тесты гоняются против одноразового Postgres (по умолчанию —
docker-контейнер на порту 55432, БД telegram_bot_test). Переопределяется
через переменную окружения TEST_DATABASE_URL.
"""

import os

import pytest_asyncio

from app.database import init_pool, close_pool, get_cursor
from app.schema import init_database

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://test:test@localhost:55432/telegram_bot_test",
)


@pytest_asyncio.fixture
async def db():
    """Чистая схема на каждый тест: инициализирует пул, создаёт таблицы, чистит данные."""
    await init_pool(TEST_DATABASE_URL)
    await init_database()
    # TRUNCATE базовых таблиц с CASCADE вычищает и все зависимые (messages,
    # join_requests, spam_users) — не нужно перечислять их явно.
    async with get_cursor() as cur:
        await cur.execute("TRUNCATE chats, users RESTART IDENTITY CASCADE;")
    try:
        yield
    finally:
        await close_pool()
