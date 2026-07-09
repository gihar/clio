"""Integration-тесты app/join_requests.py вокруг единого словаря статусов
JoinRequestStatus (PRD-06): UPSERT сбрасывает статус в pending, mark/get
работают через enum, CHECK-констрейнт БД не дрейфует от enum.
"""

import re
from datetime import datetime, timezone

from telegram import Chat, User

from app.database import get_cursor
from app.ingest import save_chat, save_user
from app.join_request_status import JoinRequestStatus
from app.join_requests import (
    save_join_request_fields,
    mark_join_requests_status,
    get_pending_fresh_join_requests,
    get_join_requests,
)

CHAT = Chat(id=-100555, type="supergroup", title="Join requests test")
APPLICANT = User(id=42, is_bot=False, first_name="Applicant")
REQUEST_DATE = datetime(2026, 7, 9, 10, 0, tzinfo=timezone.utc)


async def _status_of(request_id: int) -> str:
    async with get_cursor() as cur:
        await cur.execute("SELECT status FROM join_requests WHERE id = %s", (request_id,))
        row = await cur.fetchone()
    assert row is not None
    return row[0]


async def test_mark_join_requests_status_writes_enum_value_as_string(db):
    """T-3: mark_join_requests_status с членом enum пишет ожидаемую строку в БД."""
    await save_chat(CHAT)
    await save_user(APPLICANT)
    request_id = await save_join_request_fields(
        user_id=APPLICANT.id,
        chat_id=CHAT.id,
        username=APPLICANT.username,
        first_name=APPLICANT.first_name,
        bio=None,
        request_date=REQUEST_DATE,
    )

    updated = await mark_join_requests_status([request_id], JoinRequestStatus.DECLINED)

    assert updated == 1
    assert await _status_of(request_id) == "declined"


async def test_upsert_resets_status_to_pending_on_repeat_request(db):
    """Инвариант #1: повторная заявка (тот же user_id/chat_id) сбрасывает status в pending,
    даже если предыдущая заявка была отклонена."""
    await save_chat(CHAT)
    await save_user(APPLICANT)
    request_id = await save_join_request_fields(
        user_id=APPLICANT.id,
        chat_id=CHAT.id,
        username=APPLICANT.username,
        first_name=APPLICANT.first_name,
        bio=None,
        request_date=REQUEST_DATE,
    )
    await mark_join_requests_status([request_id], JoinRequestStatus.DECLINED)
    assert await _status_of(request_id) == "declined"

    same_row_id = await save_join_request_fields(
        user_id=APPLICANT.id,
        chat_id=CHAT.id,
        username=APPLICANT.username,
        first_name=APPLICANT.first_name,
        bio=None,
        request_date=REQUEST_DATE,
    )

    assert same_row_id == request_id
    assert await _status_of(request_id) == "pending"


async def test_get_pending_fresh_join_requests_excludes_non_pending(db):
    """get_pending_fresh_join_requests фильтрует по status=pending (не declined/expired)."""
    fresh_declined = User(id=8_000_000_001, is_bot=False, first_name="Declined")
    fresh_pending = User(id=8_000_000_002, is_bot=False, first_name="Pending")
    await save_chat(CHAT)
    await save_user(fresh_declined)
    await save_user(fresh_pending)

    declined_id = await save_join_request_fields(
        user_id=fresh_declined.id, chat_id=CHAT.id, username=None,
        first_name=fresh_declined.first_name, bio=None, request_date=REQUEST_DATE,
    )
    await mark_join_requests_status([declined_id], JoinRequestStatus.DECLINED)

    await save_join_request_fields(
        user_id=fresh_pending.id, chat_id=CHAT.id, username=None,
        first_name=fresh_pending.first_name, bio=None, request_date=REQUEST_DATE,
    )

    pending = await get_pending_fresh_join_requests(CHAT.id, min_user_id=8_000_000_000, limit=10)

    assert [row["user_id"] for row in pending] == [fresh_pending.id]


async def test_get_join_requests_filters_by_status_enum_member(db):
    """get_join_requests(status=JoinRequestStatus.X) фильтрует ровно по этому статусу."""
    other = User(id=43, is_bot=False, first_name="Other")
    await save_chat(CHAT)
    await save_user(APPLICANT)
    await save_user(other)

    pending_id = await save_join_request_fields(
        user_id=APPLICANT.id, chat_id=CHAT.id, username=None,
        first_name=APPLICANT.first_name, bio=None, request_date=REQUEST_DATE,
    )
    declined_id = await save_join_request_fields(
        user_id=other.id, chat_id=CHAT.id, username=None,
        first_name=other.first_name, bio=None, request_date=REQUEST_DATE,
    )
    await mark_join_requests_status([declined_id], JoinRequestStatus.DECLINED)

    declined_rows = await get_join_requests(CHAT.id, status=JoinRequestStatus.DECLINED)
    pending_rows = await get_join_requests(CHAT.id, status=JoinRequestStatus.PENDING)

    assert [row["id"] for row in declined_rows] == [declined_id]
    assert [row["id"] for row in pending_rows] == [pending_id]


async def test_check_constraint_values_match_enum(db):
    """T-2: FR-3(б) — DDL остаётся литеральным, но допустимые значения
    CHECK-констрейнта ck_join_requests_status (читаем из pg_constraint) не должны
    дрейфовать от множества значений JoinRequestStatus."""
    async with get_cursor() as cur:
        await cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_join_requests_status'"
        )
        row = await cur.fetchone()

    assert row is not None, "CHECK-констрейнт ck_join_requests_status не найден в схеме"
    db_values = set(re.findall(r"'(\w+)'::character varying", row[0]))

    assert db_values == set(JoinRequestStatus)
