"""Спам-пометки: юзеры, замученные антиспам-ботом, исключаются из аналитических выборок."""

from datetime import datetime
from typing import Optional

from telegram import User, Chat

from .database import get_cursor
from .ingest import save_user, save_chat


async def flag_spam_user(
    chat_id: int,
    user_id: int,
    muted_at: datetime,
    muted_by: Optional[int] = None,
    *,
    user: Optional[User] = None,
    chat: Optional[Chat] = None,
) -> None:
    """Помечает юзера как спамера в чате (UPSERT по (chat_id, user_id)).

    Если переданы объекты user/chat из события — апсертит их в users/chats,
    чтобы FK на spam_users выполнялся даже если сообщений спамера ещё не было.
    """
    if user is not None:
        await save_user(user)
    if chat is not None:
        await save_chat(chat)

    async with get_cursor() as cur:
        await cur.execute(
            """
            INSERT INTO spam_users (chat_id, user_id, muted_at, muted_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (chat_id, user_id) DO UPDATE SET
                muted_at = EXCLUDED.muted_at,
                muted_by = EXCLUDED.muted_by;
            """,
            (chat_id, user_id, muted_at, muted_by),
        )


async def unflag_spam_user(chat_id: int, user_id: int) -> None:
    """Снимает спам-пометку с юзера (размут). No-op, если пометки не было."""
    async with get_cursor() as cur:
        await cur.execute(
            "DELETE FROM spam_users WHERE chat_id = %s AND user_id = %s;",
            (chat_id, user_id),
        )
