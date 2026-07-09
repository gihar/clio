"""Integration-тест склейки process_pending_fresh_join_requests (PRD-06, T-1):
покрывает ветвление handlers.py:229,235, где статус пишется через JoinRequestStatus
вместо голых строк "declined"/"expired" — обе ветки должны сохранить прежнее
поведение (какая строка пишется в БД и в лог-файл).
"""

from datetime import datetime, timezone

import pytest
from telegram import Chat, User
from telegram.error import BadRequest

from app.bot.handlers import process_pending_fresh_join_requests
from app.database import get_cursor
from app.ingest import save_chat, save_user
from app.join_requests import save_join_request_fields

CHAT = Chat(id=-100777, type="supergroup", title="Join handler test")
REQUEST_DATE = datetime(2026, 7, 9, 10, 0, tzinfo=timezone.utc)


class _FakeBot:
    def __init__(self, outcome: str):
        self._outcome = outcome  # "decline" | "expired"
        self.calls = []

    async def decline_chat_join_request(self, chat_id: int, user_id: int):
        self.calls.append((chat_id, user_id))
        if self._outcome == "expired":
            raise BadRequest("Bad Request: CHAT_JOIN_REQUEST_NOT_FOUND")
        return True


async def _make_fresh_request(user_id: int) -> int:
    user = User(id=user_id, is_bot=False, first_name="Fresh")
    await save_user(user)
    return await save_join_request_fields(
        user_id=user_id,
        chat_id=CHAT.id,
        username=None,
        first_name=user.first_name,
        bio=None,
        request_date=REQUEST_DATE,
    )


async def _status_of(request_id: int) -> str:
    async with get_cursor() as cur:
        await cur.execute("SELECT status FROM join_requests WHERE id = %s", (request_id,))
        row = await cur.fetchone()
    assert row is not None
    return row[0]


async def test_declines_pending_request_and_writes_declined_status(db, tmp_path):
    """Успешный decline_chat_join_request -> статус 'declined' + строка в логе."""
    await save_chat(CHAT)
    request_id = await _make_fresh_request(8_000_000_100)
    bot = _FakeBot(outcome="decline")
    log_path = tmp_path / "declined.log"

    declined, processed = await process_pending_fresh_join_requests(
        bot, CHAT.id, threshold=8_000_000_000, limit=10, log_path=str(log_path),
    )

    assert (declined, processed) == (1, 1)
    assert bot.calls == [(CHAT.id, 8_000_000_100)]
    assert await _status_of(request_id) == "declined"

    log_line = log_path.read_text(encoding="utf-8")
    assert "\tdeclined\t" in log_line
    assert f"request_id={request_id}" in log_line


async def test_expired_join_request_error_writes_expired_status(db, tmp_path):
    """decline_chat_join_request падает с 'not found' -> статус 'expired' + строка в логе."""
    await save_chat(CHAT)
    request_id = await _make_fresh_request(8_000_000_200)
    bot = _FakeBot(outcome="expired")
    log_path = tmp_path / "declined.log"

    declined, processed = await process_pending_fresh_join_requests(
        bot, CHAT.id, threshold=8_000_000_000, limit=10, log_path=str(log_path),
    )

    assert (declined, processed) == (0, 1)
    assert await _status_of(request_id) == "expired"

    log_line = log_path.read_text(encoding="utf-8")
    assert "\texpired\t" in log_line
    assert f"request_id={request_id}" in log_line
