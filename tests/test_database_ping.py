"""Integration-тесты app.database.ping() (FR-5 из PRD-05)."""

from app.database import close_pool, ping


async def test_ping_returns_true_when_database_reachable(db):
    assert await ping() is True


async def test_ping_returns_false_when_pool_not_initialized():
    await close_pool()  # гарантирует чистое состояние вне зависимости от порядка тестов

    assert await ping() is False
