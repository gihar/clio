"""Integration-тесты границ модуля app/message_reads (T-2 из PRD-01)."""

from datetime import datetime, timedelta, timezone

from telegram import User, Chat

from app.ingest import save_user, save_chat
from app.message_reads.digest import get_messages_for_summary
from app.message_reads.raw import get_chat_messages, get_chat_messages_by_date
from app.database import get_cursor

CHAT = Chat(id=-100555, type="supergroup", title="Message reads boundary test")
ALICE = User(id=1, is_bot=False, first_name="Alice")


async def _insert_message(
    message_id: int,
    user_id: int,
    text,
    sent_at: datetime,
    message_type: str = "text",
):
    async with get_cursor() as cur:
        await cur.execute(
            """
            INSERT INTO messages (message_id, chat_id, user_id, message_type, text, sent_at)
            VALUES (%s, %s, %s, %s, %s, %s);
            """,
            (message_id, CHAT.id, user_id, message_type, text, sent_at),
        )


async def test_summary_window_excludes_message_older_than_24h(db):
    """Сообщение старше 24ч не попадает в digest-выборку саммари."""
    await save_chat(CHAT)
    await save_user(ALICE)

    now = datetime.now(timezone.utc)
    await _insert_message(1, ALICE.id, "recent message", now - timedelta(hours=1))
    await _insert_message(2, ALICE.id, "old message", now - timedelta(hours=25))

    texts = [m["text"] for m in await get_messages_for_summary(CHAT.id)]

    assert "recent message" in texts
    assert "old message" not in texts


async def test_raw_messages_pagination_and_type_filter(db):
    """get_chat_messages: фильтр по типу сообщения и лимит/оффсет пагинации."""
    await save_chat(CHAT)
    await save_user(ALICE)

    now = datetime.now(timezone.utc)
    await _insert_message(10, ALICE.id, "text one", now - timedelta(minutes=4))
    await _insert_message(11, ALICE.id, "text two", now - timedelta(minutes=3))
    await _insert_message(12, ALICE.id, "text three", now - timedelta(minutes=2))
    await _insert_message(13, ALICE.id, None, now - timedelta(minutes=1), message_type="photo")

    text_messages = await get_chat_messages(CHAT.id, message_type="text")
    assert len(text_messages) == 3
    assert all(m["message_type"] == "text" for m in text_messages)

    # DESC order: самое новое сообщение первое.
    page1 = await get_chat_messages(CHAT.id, limit=2, offset=0, message_type="text")
    assert [m["text"] for m in page1] == ["text three", "text two"]

    page2 = await get_chat_messages(CHAT.id, limit=2, offset=2, message_type="text")
    assert [m["text"] for m in page2] == ["text one"]


async def test_raw_messages_for_day_boundary_is_legacy_utc_minus_3(db):
    """Пин текущей (баговой) границы дня, унаследованной бит-в-бит из app/models.py.

    Формула `(sent_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Moscow')::date`
    на TIMESTAMPTZ-колонке ``sent_at`` двигает границу дня на 03:00 UTC
    (фактически UTC-3), а не на 21:00 UTC предыдущего дня, как подразумевает
    "московский" (UTC+3) в названии. Это существующий баг продакшн-кода,
    предшествующий PRD-01; FR-6 требует сохранить семантику ТОЧНО, поэтому
    тест фиксирует фактическое поведение, а не намеченное. Фикс — отдельный
    тикет вне скоупа PRD-01: https://github.com/gihar/clio/issues/9.
    """
    await save_chat(CHAT)
    await save_user(ALICE)

    # 02:59 UTC -> текущий каст относит к предыдущему дню (граница проходит
    # по 03:00 UTC, а не по 21:00 UTC, как было бы при корректном UTC+3).
    before_boundary = datetime(2026, 7, 8, 2, 59, tzinfo=timezone.utc)
    at_boundary = datetime(2026, 7, 8, 3, 0, tzinfo=timezone.utc)
    await _insert_message(20, ALICE.id, "before 03:00 utc", before_boundary)
    await _insert_message(21, ALICE.id, "at 03:00 utc", at_boundary)

    previous_day = await get_chat_messages_by_date(CHAT.id, "2026-07-07")
    same_day = await get_chat_messages_by_date(CHAT.id, "2026-07-08")

    assert [m["text"] for m in previous_day] == ["before 03:00 utc"]
    assert [m["text"] for m in same_day] == ["at 03:00 utc"]
