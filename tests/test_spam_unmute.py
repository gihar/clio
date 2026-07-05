"""Integration-тесты размута: снятие спам-пометки возвращает юзера в дайджест."""

from datetime import datetime, timezone

from telegram import User, Chat

from app.models import (
    flag_spam_user,
    unflag_spam_user,
    save_user,
    save_chat,
    get_messages_for_summary,
)
from app.database import get_cursor

CHAT = Chat(id=-100888, type="supergroup", title="Unmute test")
ALICE = User(id=1, is_bot=False, first_name="Alice")
SPAMMER = User(id=999, is_bot=False, first_name="Spammer")
MUTED_AT = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)


async def test_unflag_removes_spam_row(db):
    """unflag_spam_user удаляет строку из spam_users."""
    await flag_spam_user(
        chat_id=CHAT.id, user_id=SPAMMER.id, muted_at=MUTED_AT,
        muted_by=555, user=SPAMMER, chat=CHAT,
    )

    await unflag_spam_user(chat_id=CHAT.id, user_id=SPAMMER.id)

    async with get_cursor() as cur:
        await cur.execute(
            "SELECT 1 FROM spam_users WHERE chat_id = %s AND user_id = %s",
            (CHAT.id, SPAMMER.id),
        )
        assert await cur.fetchone() is None


async def test_unflag_missing_row_is_noop(db):
    """Снятие несуществующей пометки — no-op без ошибки."""
    await unflag_spam_user(chat_id=-100999, user_id=424242)


async def test_unmute_restores_messages_to_summary(db):
    """После размута сообщения бывшего спамера снова попадают в саммари."""
    await save_chat(CHAT)
    await save_user(ALICE)
    await save_user(SPAMMER)
    async with get_cursor() as cur:
        await cur.execute(
            "INSERT INTO messages (message_id, chat_id, user_id, message_type, text, sent_at) "
            "VALUES (1, %s, %s, 'text', 'hello from alice', NOW()), "
            "(2, %s, %s, 'text', 'SPAM buy now', NOW());",
            (CHAT.id, ALICE.id, CHAT.id, SPAMMER.id),
        )
    await flag_spam_user(chat_id=CHAT.id, user_id=SPAMMER.id, muted_at=MUTED_AT, muted_by=555)

    # пока помечен — исключён
    before = [m["text"] for m in await get_messages_for_summary(CHAT.id)]
    assert "SPAM buy now" not in before

    await unflag_spam_user(chat_id=CHAT.id, user_id=SPAMMER.id)

    after = [m["text"] for m in await get_messages_for_summary(CHAT.id)]
    assert "SPAM buy now" in after
    assert "hello from alice" in after
