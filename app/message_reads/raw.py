"""Raw выборки сообщений: НЕ фильтруют помеченных спамеров.

Используются сырой вьюхой админки и экспортом. Скоуп зафиксирован
tests/test_spam_filtering.py:70 — намеренно не исключают спам.
См. докстринг ``app.message_reads`` про инвариант digest vs raw.
"""

import logging
from typing import Any, Dict, List, Optional

from ..database import get_cursor
from . import FULL_MESSAGE_COLUMNS_SQL, MOSCOW_DAY_SQL, row_to_full_message

logger = logging.getLogger(__name__)


async def get_chat_messages(
    chat_id: int,
    limit: int = 100,
    offset: int = 0,
    message_type: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Получает сообщения чата."""
    async with get_cursor() as cur:
        query = f"""
            SELECT {FULL_MESSAGE_COLUMNS_SQL}
            FROM messages m
            LEFT JOIN users u ON m.user_id = u.id
            WHERE m.chat_id = %s
        """
        params = [chat_id]

        if message_type:
            query += " AND m.message_type = %s"
            params.append(message_type)

        query += " ORDER BY m.sent_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        await cur.execute(query, params)
        rows = await cur.fetchall()

        return [row_to_full_message(row) for row in rows]


async def get_chat_messages_by_date(
    chat_id: int,
    date_str: str,  # format: YYYY-MM-DD
) -> List[Dict[str, Any]]:
    """Получает все сообщения чата за конкретный календарный день (UTC+3)."""
    async with get_cursor() as cur:
        # UTC+3: день начинается в 00:00 UTC+3 = 21:00 UTC предыдущего дня
        await cur.execute(f"""
            SELECT {FULL_MESSAGE_COLUMNS_SQL}
            FROM messages m
            LEFT JOIN users u ON m.user_id = u.id
            WHERE m.chat_id = %s
              AND {MOSCOW_DAY_SQL} = %s::date
            ORDER BY m.sent_at ASC
        """, (chat_id, date_str))

        rows = await cur.fetchall()
        return [row_to_full_message(row) for row in rows]


async def get_chat_messages_by_date_range(
    chat_id: int,
    date_from: str,  # format: YYYY-MM-DD
    date_to: str,    # format: YYYY-MM-DD
) -> List[Dict[str, Any]]:
    """Получает все сообщения чата за диапазон дат (включительно, UTC+3)."""
    async with get_cursor() as cur:
        await cur.execute(f"""
            SELECT {FULL_MESSAGE_COLUMNS_SQL}
            FROM messages m
            LEFT JOIN users u ON m.user_id = u.id
            WHERE m.chat_id = %s
              AND {MOSCOW_DAY_SQL} >= %s::date
              AND {MOSCOW_DAY_SQL} <= %s::date
            ORDER BY m.sent_at ASC
        """, (chat_id, date_from, date_to))

        rows = await cur.fetchall()
        return [row_to_full_message(row) for row in rows]
