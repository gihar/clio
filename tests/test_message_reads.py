"""Integration-тесты границ модуля app/message_reads (T-2 из PRD-01)."""

from datetime import datetime, timedelta, timezone

from telegram import User, Chat

from app.database import get_cursor
from app.ingest import save_user, save_chat, record_message
from app.message_reads._shared import MOSCOW_DAY_SQL
from app.message_reads.digest import get_daily_message_counts, get_messages_for_summary
from app.message_reads.raw import get_chat_messages, get_chat_messages_by_date

CHAT = Chat(id=-100555, type="supergroup", title="Message reads boundary test")
ALICE = User(id=1, is_bot=False, first_name="Alice")


async def _insert_message(
    message_id: int,
    user_id: int,
    text,
    sent_at: datetime,
    message_type: str = "text",
):
    await record_message(
        chat_id=CHAT.id,
        message_id=message_id,
        user_id=user_id,
        sent_at=sent_at,
        message_type=message_type,
        text=text,
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


async def test_raw_messages_for_day_boundary_is_moscow_utc_plus_3(db):
    """Пин исправленной границы дня: московские сутки переключаются в 21:00 UTC.

    Формула `(sent_at AT TIME ZONE 'Europe/Moscow')::date` на TIMESTAMPTZ-колонке
    ``sent_at`` даёт единственный каст временной зоны -- naive-timestamp в
    московском локальном времени, чей ::date детерминирован и не зависит от
    session TimeZone. Граница дня верно проходит по 21:00 UTC (UTC+3), а не по
    03:00 UTC, как было при легаси-баге (см. https://github.com/gihar/clio/issues/9).
    """
    await save_chat(CHAT)
    await save_user(ALICE)

    # 20:59 UTC -> ещё московский день D (23:59 MSK, до полуночи).
    before_boundary = datetime(2026, 7, 8, 20, 59, tzinfo=timezone.utc)
    # 21:00 UTC -> уже московский день D+1 (00:00 MSK).
    at_boundary = datetime(2026, 7, 8, 21, 0, tzinfo=timezone.utc)
    await _insert_message(20, ALICE.id, "before 21:00 utc", before_boundary)
    await _insert_message(21, ALICE.id, "at 21:00 utc", at_boundary)

    same_day = await get_chat_messages_by_date(CHAT.id, "2026-07-08")
    next_day = await get_chat_messages_by_date(CHAT.id, "2026-07-09")

    assert [m["text"] for m in same_day] == ["before 21:00 utc"]
    assert [m["text"] for m in next_day] == ["at 21:00 utc"]


async def test_daily_message_counts_day_boundary_is_moscow_utc_plus_3(db):
    """get_daily_message_counts тоже группирует по исправленной московской границе.

    02:59 и 03:00 UTC одного и того же UTC-дня раньше (легаси-баг) попадали в
    РАЗНЫЕ московские дни (граница была на 03:00 UTC); после фикса оба
    относятся к ОДНОМУ московскому дню, а 21:00 UTC того же дня уже уходит в
    следующий (см. https://github.com/gihar/clio/issues/9).
    """
    await save_chat(CHAT)
    await save_user(ALICE)

    await _insert_message(30, ALICE.id, "02:59 utc", datetime(2026, 7, 8, 2, 59, tzinfo=timezone.utc))
    await _insert_message(31, ALICE.id, "03:00 utc", datetime(2026, 7, 8, 3, 0, tzinfo=timezone.utc))
    await _insert_message(32, ALICE.id, "21:00 utc", datetime(2026, 7, 8, 21, 0, tzinfo=timezone.utc))

    counts = {c["date"]: c["count"] for c in await get_daily_message_counts(CHAT.id, days=3)}

    assert counts.get("2026-07-08") == 2
    assert counts.get("2026-07-09") == 1


async def test_moscow_day_sql_is_independent_of_session_timezone(db):
    """MOSCOW_DAY_SQL даёт одинаковый московский день независимо от session TimeZone.

    Легаси-баг (двойной AT TIME ZONE) был подвержен этой зависимости, потому что
    его финальный ::date каст применялся к TIMESTAMPTZ-результату промежуточного
    выражения. Однократный `AT TIME ZONE 'Europe/Moscow'` на TIMESTAMPTZ-колонке
    сразу даёт naive-timestamp, чей ::date уже не привязан к session TimeZone
    (см. https://github.com/gihar/clio/issues/9).
    """
    at_boundary = datetime(2026, 7, 8, 21, 0, tzinfo=timezone.utc)
    select_expr = MOSCOW_DAY_SQL.replace("m.sent_at", "%s::timestamptz")

    async with get_cursor() as cur:
        await cur.execute("SET TIME ZONE 'UTC'")
        await cur.execute(f"SELECT {select_expr}", (at_boundary,))
        (utc_session_day,) = await cur.fetchone()

        await cur.execute("SET TIME ZONE 'America/New_York'")
        await cur.execute(f"SELECT {select_expr}", (at_boundary,))
        (ny_session_day,) = await cur.fetchone()

    assert utc_session_day == ny_session_day == datetime(2026, 7, 9).date()
