"""Integration-тесты хранения спам-пометок (нужен Postgres — фикстура db)."""

from datetime import datetime, timezone

from telegram import User, Chat

from app.spam_flags import flag_spam_user
from app.database import get_cursor


async def test_flag_spam_user_writes_row_and_is_fk_safe(db):
    """flag_spam_user создаёт строку, апсертя user/chat из события.

    FK-safe: работает, даже если сообщений спамера в БД ещё не было.
    """
    chat = Chat(id=-100123, type="supergroup", title="Test chat")
    spammer = User(id=999, is_bot=False, first_name="Spammer")
    muted_at = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)

    await flag_spam_user(
        chat_id=chat.id,
        user_id=spammer.id,
        muted_at=muted_at,
        muted_by=555,
        user=spammer,
        chat=chat,
    )

    async with get_cursor() as cur:
        await cur.execute(
            "SELECT chat_id, user_id, muted_by FROM spam_users "
            "WHERE chat_id = %s AND user_id = %s",
            (chat.id, spammer.id),
        )
        row = await cur.fetchone()

    assert row is not None
    assert row[0] == chat.id
    assert row[1] == spammer.id
    assert row[2] == 555


async def test_flag_spam_user_is_idempotent(db):
    """Повторный мут того же юзера не плодит дубль, а обновляет muted_at/muted_by."""
    chat = Chat(id=-100123, type="supergroup", title="Test chat")
    spammer = User(id=999, is_bot=False, first_name="Spammer")
    first = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
    second = datetime(2026, 7, 5, 13, 30, tzinfo=timezone.utc)

    await flag_spam_user(chat_id=chat.id, user_id=spammer.id, muted_at=first,
                         muted_by=555, user=spammer, chat=chat)
    await flag_spam_user(chat_id=chat.id, user_id=spammer.id, muted_at=second,
                         muted_by=777, user=spammer, chat=chat)

    async with get_cursor() as cur:
        await cur.execute(
            "SELECT muted_at, muted_by FROM spam_users "
            "WHERE chat_id = %s AND user_id = %s",
            (chat.id, spammer.id),
        )
        rows = await cur.fetchall()

    assert len(rows) == 1
    assert rows[0][0] == second
    assert rows[0][1] == 777
