"""Integration-тесты: аналитические выборки исключают помеченных спамеров."""

from datetime import datetime, timezone

from telegram import User, Chat

from app.models import (
    flag_spam_user,
    save_user,
    save_chat,
    get_messages_for_summary,
    get_messages_for_period,
    get_chat_messages,
)
from app.database import get_cursor

CHAT = Chat(id=-100777, type="supergroup", title="Filter test")
ALICE = User(id=1, is_bot=False, first_name="Alice")
SPAMMER = User(id=999, is_bot=False, first_name="Spammer")


async def _insert_message(message_id: int, user_id: int, text: str):
    """Вставляет текстовое сообщение 'сейчас' (попадает в окно 24ч)."""
    async with get_cursor() as cur:
        await cur.execute(
            """
            INSERT INTO messages (message_id, chat_id, user_id, message_type, text, sent_at)
            VALUES (%s, %s, %s, 'text', %s, NOW());
            """,
            (message_id, CHAT.id, user_id, text),
        )


async def _seed_chat_with_flagged_spammer():
    """Чат с двумя авторами (Alice + Spammer), где Spammer помечен как спамер."""
    await save_chat(CHAT)
    await save_user(ALICE)
    await save_user(SPAMMER)
    await _insert_message(1, ALICE.id, "hello from alice")
    await _insert_message(2, SPAMMER.id, "SPAM buy now")
    await flag_spam_user(
        chat_id=CHAT.id,
        user_id=SPAMMER.id,
        muted_at=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
        muted_by=555,
    )


async def test_summary_excludes_flagged_spammer(db):
    """Сообщения замученного спамера не попадают в суточное саммари."""
    await _seed_chat_with_flagged_spammer()

    texts = [m["text"] for m in await get_messages_for_summary(CHAT.id)]

    assert "hello from alice" in texts
    assert "SPAM buy now" not in texts


async def test_period_strategy_excludes_flagged_spammer(db):
    """Сообщения спамера не попадают в выборку за период (стратегия неделя/месяц)."""
    await _seed_chat_with_flagged_spammer()

    texts = [m["text"] for m in await get_messages_for_period(CHAT.id, days=7)]

    assert "hello from alice" in texts
    assert "SPAM buy now" not in texts


async def test_raw_admin_view_still_shows_flagged_spammer(db):
    """Скоуп: сырая вьюха админки не фильтрует спам — он остаётся виден."""
    await _seed_chat_with_flagged_spammer()

    texts = [m["text"] for m in await get_chat_messages(CHAT.id)]

    assert "hello from alice" in texts
    assert "SPAM buy now" in texts
