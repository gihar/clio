"""Заявки на вступление: авто-отклонение "свежих" аккаунтов и админ-инспекция."""

from datetime import datetime
from typing import Optional, List, Dict, Any

from telegram import User, Chat

from .database import get_cursor
from .ingest import save_user, save_chat


async def save_join_request_fields(
    user_id: int,
    chat_id: int,
    username: Optional[str],
    first_name: Optional[str],
    bio: Optional[str],
    request_date: datetime,
    *,
    user: Optional[User] = None,
    chat: Optional[Chat] = None,
) -> Optional[int]:
    """Save (UPSERT) join request by (user_id, chat_id).

    If user/chat objects are provided, we also upsert them into users/chats tables
    so FK constraints on join_requests are satisfied.
    """
    if user is not None:
        await save_user(user)
    if chat is not None:
        await save_chat(chat)

    async with get_cursor() as cur:
        await cur.execute(
            """
            INSERT INTO join_requests (user_id, chat_id, username, first_name, bio, request_date, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending')
            ON CONFLICT (user_id, chat_id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                bio = EXCLUDED.bio,
                request_date = EXCLUDED.request_date,
                status = 'pending'
            RETURNING id;
            """,
            (user_id, chat_id, username, first_name, bio, request_date),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else None


async def get_pending_fresh_join_requests(chat_id: int, min_user_id: int, limit: int) -> List[Dict[str, Any]]:
    """Get pending join requests for chat with user_id >= threshold."""
    async with get_cursor() as cur:
        await cur.execute(
            """
            SELECT id, user_id, chat_id, username, first_name, request_date
            FROM join_requests
            WHERE chat_id = %s
              AND status = 'pending'
              AND user_id >= %s
            ORDER BY request_date ASC
            LIMIT %s;
            """,
            (chat_id, min_user_id, limit),
        )
        rows = await cur.fetchall()

    return [
        {
            "id": row[0],
            "user_id": row[1],
            "chat_id": row[2],
            "username": row[3],
            "first_name": row[4],
            "request_date": row[5],
        }
        for row in rows
    ]


async def mark_join_requests_status(ids: List[int], status: str) -> int:
    """Update join_requests.status for given primary keys, return updated count."""
    if not ids:
        return 0

    async with get_cursor() as cur:
        await cur.execute(
            "UPDATE join_requests SET status = %s WHERE id = ANY(%s::bigint[]);",
            (status, ids),
        )
        return int(cur.rowcount or 0)


async def get_join_requests(
    chat_id: int,
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Get join requests for a chat (for admin/API inspection)."""
    async with get_cursor() as cur:
        query = """
            SELECT
                id,
                user_id,
                chat_id,
                username,
                first_name,
                bio,
                request_date,
                status,
                created_at
            FROM join_requests
            WHERE chat_id = %s
        """
        params: List[Any] = [chat_id]

        if status:
            query += " AND status = %s"
            params.append(status)

        query += " ORDER BY request_date DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        await cur.execute(query, params)
        rows = await cur.fetchall()

    return [
        {
            "id": row[0],
            "user_id": row[1],
            "chat_id": row[2],
            "username": row[3],
            "first_name": row[4],
            "bio": row[5],
            "request_date": row[6],
            "status": row[7],
            "created_at": row[8],
        }
        for row in rows
    ]
