"""Integration-тесты: аналитические выборки исключают помеченных спамеров."""

from datetime import datetime, timezone

from telegram import User, Chat

from app.spam_flags import flag_spam_user
from app.ingest import save_user, save_chat, record_message
from app.message_reads.digest import (
    get_messages_for_summary,
    get_messages_for_period,
    get_daily_message_counts,
)
from app.message_reads.raw import get_chat_messages

CHAT = Chat(id=-100777, type="supergroup", title="Filter test")
ALICE = User(id=1, is_bot=False, first_name="Alice")
SPAMMER = User(id=999, is_bot=False, first_name="Spammer")


async def _insert_message(message_id: int, user_id: int, text: str):
    """Вставляет текстовое сообщение 'сейчас' (попадает в окно 24ч)."""
    await record_message(
        chat_id=CHAT.id,
        message_id=message_id,
        user_id=user_id,
        sent_at=datetime.now(timezone.utc),
        text=text,
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


async def test_daily_counts_exclude_flagged_spammer(db):
    """Недельная активность (идёт в LLM-аналитику) не учитывает сообщения спамера."""
    await _seed_chat_with_flagged_spammer()

    counts = await get_daily_message_counts(CHAT.id, days=7)
    total = sum(c["count"] for c in counts)

    assert total == 1  # только Alice; сообщение спамера исключено


async def test_flag_is_chat_scoped(db):
    """Пометка спамера скоупится по чату: замученный в чате A виден в чате B."""
    chat_b = Chat(id=-100999, type="supergroup", title="Other chat")
    await save_chat(CHAT)
    await save_chat(chat_b)
    await save_user(SPAMMER)
    await record_message(
        chat_id=CHAT.id, message_id=10, user_id=SPAMMER.id,
        sent_at=datetime.now(timezone.utc), text="msg in chat A",
    )
    await record_message(
        chat_id=chat_b.id, message_id=11, user_id=SPAMMER.id,
        sent_at=datetime.now(timezone.utc), text="msg in chat B",
    )
    # мутим спамера ТОЛЬКО в чате A
    await flag_spam_user(
        chat_id=CHAT.id, user_id=SPAMMER.id,
        muted_at=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc), muted_by=555,
    )

    a_texts = [m["text"] for m in await get_messages_for_summary(CHAT.id)]
    b_texts = [m["text"] for m in await get_messages_for_summary(chat_b.id)]

    assert "msg in chat A" not in a_texts   # исключён в A
    assert "msg in chat B" in b_texts        # но виден в B — пометка скоупится по чату
