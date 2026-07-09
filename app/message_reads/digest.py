"""Digest-выборки: исключают помеченных спамеров (spam_users) — для саммари, стратегии, аналитики."""

import logging
from typing import Any, Dict, List

from ..database import get_cursor
from ._shared import MOSCOW_DAY_SQL, SPAM_EXCLUSION_SQL

logger = logging.getLogger(__name__)


async def get_messages_for_summary(chat_id: int, limit: int = 500) -> List[Dict[str, Any]]:
    """Получает сообщения за последние 24 часа для генерации саммари."""
    async with get_cursor() as cur:
        await cur.execute(f"""
            SELECT
                m.text,
                COALESCE(u.username, u.first_name, 'Unknown') as author,
                m.sent_at
            FROM messages m
            LEFT JOIN users u ON m.user_id = u.id
            WHERE m.chat_id = %s
              AND m.sent_at >= NOW() - INTERVAL '24 hours'
              AND m.text IS NOT NULL
              {SPAM_EXCLUSION_SQL}
            ORDER BY m.sent_at ASC
            LIMIT %s
        """, (chat_id, limit))

        rows = await cur.fetchall()
        return [
            {"text": row[0], "author": row[1], "sent_at": row[2]}
            for row in rows
        ]


async def get_daily_message_counts(chat_id: int, days: int = 7) -> List[Dict[str, Any]]:
    """Получает количество сообщений по московским дням за последние N дней."""
    async with get_cursor() as cur:
        await cur.execute(f"""
            SELECT
                {MOSCOW_DAY_SQL} as day,
                COUNT(*) as count
            FROM messages m
            WHERE m.chat_id = %s
              AND m.sent_at >= NOW() - make_interval(days => %s)
              {SPAM_EXCLUSION_SQL}
            GROUP BY day
            ORDER BY day ASC
        """, (chat_id, days))

        rows = await cur.fetchall()
        return [
            {"date": row[0].isoformat(), "count": row[1]}
            for row in rows
        ]


async def get_messages_for_period(
    chat_id: int,
    days: int,
    limit: int = 500
) -> List[Dict[str, Any]]:
    """Получает сообщения за указанный период для анализа."""
    async with get_cursor() as cur:
        await cur.execute(f"""
            SELECT
                m.text,
                m.caption,
                COALESCE(u.username, u.first_name, 'Unknown') as author,
                m.sent_at,
                m.message_type
            FROM messages m
            LEFT JOIN users u ON m.user_id = u.id
            WHERE m.chat_id = %s
              AND m.sent_at >= NOW() - make_interval(days => %s)
              AND (m.text IS NOT NULL OR m.caption IS NOT NULL)
              {SPAM_EXCLUSION_SQL}
            ORDER BY m.sent_at DESC
            LIMIT %s
        """, (chat_id, days, limit))

        rows = await cur.fetchall()
        return [
            {
                "text": row[0] or row[1],
                "author": row[2],
                "sent_at": row[3],
                "type": row[4],
            }
            for row in rows
        ]
