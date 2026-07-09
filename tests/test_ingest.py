"""Integration-тесты record_message/record_message_edit — интерфейса записи
сообщений, тестопригодного без сборки полного telegram.Message (PRD-04)."""

from datetime import datetime, timezone

import pytest
from telegram import Message, User, Chat

from app.ingest import save_user, save_chat, record_message, record_message_edit, save_message
from app.database import get_cursor

CHAT = Chat(id=-100321, type="supergroup", title="Ingest test")
ALICE = User(id=1, is_bot=False, first_name="Alice")
SENT_AT = datetime(2026, 7, 9, 10, 0, tzinfo=timezone.utc)
EDITED_AT = datetime(2026, 7, 9, 10, 5, tzinfo=timezone.utc)


async def test_record_message_writes_row(db):
    """record_message с плоскими параметрами создаёт строку в messages."""
    await save_chat(CHAT)
    await save_user(ALICE)

    await record_message(
        chat_id=CHAT.id,
        message_id=1,
        user_id=ALICE.id,
        sent_at=SENT_AT,
        text="hello",
    )

    async with get_cursor() as cur:
        await cur.execute(
            "SELECT text, message_type, sent_at FROM messages "
            "WHERE chat_id = %s AND message_id = %s",
            (CHAT.id, 1),
        )
        row = await cur.fetchone()

    assert row is not None
    assert row[0] == "hello"
    assert row[1] == "text"
    assert row[2] == SENT_AT


async def test_record_message_dedups_by_chat_and_message_id(db):
    """Повторный record_message с тем же (chat_id, message_id) — no-op."""
    await save_chat(CHAT)
    await save_user(ALICE)

    await record_message(chat_id=CHAT.id, message_id=2, user_id=ALICE.id, sent_at=SENT_AT, text="first")
    await record_message(chat_id=CHAT.id, message_id=2, user_id=ALICE.id, sent_at=SENT_AT, text="second")

    async with get_cursor() as cur:
        await cur.execute(
            "SELECT text FROM messages WHERE chat_id = %s AND message_id = %s",
            (CHAT.id, 2),
        )
        rows = await cur.fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "first"


async def test_record_message_requires_sent_at(db):
    """sent_at обязателен — без него record_message кидает ValueError (FR-5)."""
    await save_chat(CHAT)
    await save_user(ALICE)

    with pytest.raises(ValueError):
        await record_message(chat_id=CHAT.id, message_id=3, user_id=ALICE.id, sent_at=None, text="x")


async def test_record_message_requires_nonempty_message_type(db):
    """message_type — непустая строка, иначе ValueError (FR-5)."""
    await save_chat(CHAT)
    await save_user(ALICE)

    with pytest.raises(ValueError):
        await record_message(
            chat_id=CHAT.id, message_id=4, user_id=ALICE.id,
            sent_at=SENT_AT, message_type="", text="x",
        )


async def test_record_message_edit_updates_existing_row(db):
    """record_message_edit обновляет text/edited_at, не создавая новую строку."""
    await save_chat(CHAT)
    await save_user(ALICE)
    await record_message(chat_id=CHAT.id, message_id=5, user_id=ALICE.id, sent_at=SENT_AT, text="before")

    await record_message_edit(chat_id=CHAT.id, message_id=5, edited_at=EDITED_AT, text="after")

    async with get_cursor() as cur:
        await cur.execute(
            "SELECT text, edited_at FROM messages WHERE chat_id = %s AND message_id = %s",
            (CHAT.id, 5),
        )
        rows = await cur.fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "after"
    assert rows[0][1] == EDITED_AT


async def test_record_message_edit_missing_row_is_noop(db):
    """Редактирование несуществующего сообщения — тихий no-op, строка не создаётся."""
    await save_chat(CHAT)
    await save_user(ALICE)

    await record_message_edit(chat_id=CHAT.id, message_id=999, edited_at=EDITED_AT, text="ghost")

    async with get_cursor() as cur:
        await cur.execute(
            "SELECT 1 FROM messages WHERE chat_id = %s AND message_id = %s",
            (CHAT.id, 999),
        )
        assert await cur.fetchone() is None


# --- save_message: Telegram-адаптер поверх record_message/record_message_edit ---
# Характеризационные тесты: до PRD-04 у save_message не было прямого покрытия
# (его и трудно тестировать напрямую — потому и появился record_message).
# Эти тесты фиксируют наблюдаемое поведение до рефакторинга адаптера и должны
# остаться зелёными после (FR-2: сигнатура и поведение save_message не меняются).


async def test_save_message_inserts_row_from_telegram_message(db):
    """save_message(msg) апсертит user/chat и вставляет строку с полями из Message."""
    chat = Chat(id=-100654, type="supergroup", title="Adapter test")
    user = User(id=7, is_bot=False, first_name="Bob")
    msg = Message(
        message_id=100,
        date=SENT_AT,
        chat=chat,
        from_user=user,
        text="adapter hello",
    )

    await save_message(msg, is_edit=False)

    async with get_cursor() as cur:
        await cur.execute(
            "SELECT text, message_type, user_id, sent_at FROM messages "
            "WHERE chat_id = %s AND message_id = %s",
            (chat.id, 100),
        )
        row = await cur.fetchone()
        await cur.execute("SELECT 1 FROM chats WHERE id = %s", (chat.id,))
        chat_row = await cur.fetchone()
        await cur.execute("SELECT 1 FROM users WHERE id = %s", (user.id,))
        user_row = await cur.fetchone()

    assert row is not None
    assert row[0] == "adapter hello"
    assert row[1] == "text"
    assert row[2] == user.id
    assert row[3] == SENT_AT
    assert chat_row is not None
    assert user_row is not None


async def test_save_message_edit_updates_existing_row(db):
    """save_message(msg, is_edit=True) обновляет text/edited_at существующей строки."""
    chat = Chat(id=-100654, type="supergroup", title="Adapter test")
    user = User(id=7, is_bot=False, first_name="Bob")
    original = Message(message_id=101, date=SENT_AT, chat=chat, from_user=user, text="before edit")
    await save_message(original, is_edit=False)

    edited = Message(
        message_id=101, date=SENT_AT, chat=chat, from_user=user,
        text="after edit", edit_date=EDITED_AT,
    )
    await save_message(edited, is_edit=True)

    async with get_cursor() as cur:
        await cur.execute(
            "SELECT text, edited_at FROM messages WHERE chat_id = %s AND message_id = %s",
            (chat.id, 101),
        )
        rows = await cur.fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "after edit"
    assert rows[0][1] == EDITED_AT


async def test_save_message_without_from_user_is_noop(db):
    """Guard: сообщение без from_user (например, из канала) не сохраняется."""
    chat = Chat(id=-100654, type="channel", title="Channel")
    msg = Message(message_id=102, date=SENT_AT, chat=chat, text="channel post")

    await save_message(msg, is_edit=False)

    async with get_cursor() as cur:
        await cur.execute(
            "SELECT 1 FROM messages WHERE chat_id = %s AND message_id = %s",
            (chat.id, 102),
        )
        assert await cur.fetchone() is None
