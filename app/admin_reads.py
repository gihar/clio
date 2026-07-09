"""Запросы для админки: статистика, списки чатов/пользователей, дашборд."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from .database import get_cursor


# ========== Запросы для админки ==========

@dataclass
class ChatStats:
    """Статистика по чату."""
    id: int
    type: str
    title: Optional[str]
    username: Optional[str]
    message_count: int
    user_count: int
    last_message_at: Optional[datetime]
    first_seen_at: datetime


@dataclass
class Stats:
    """Общая статистика."""
    total_chats: int
    total_users: int
    total_messages: int
    messages_today: int
    messages_by_type: Dict[str, int]


async def get_stats() -> Stats:
    """Получает общую статистику."""
    async with get_cursor() as cur:
        # Общие счётчики
        await cur.execute("SELECT COUNT(*) FROM chats")
        total_chats = (await cur.fetchone())[0]
        
        await cur.execute("SELECT COUNT(*) FROM users")
        total_users = (await cur.fetchone())[0]
        
        await cur.execute("SELECT COUNT(*) FROM messages")
        total_messages = (await cur.fetchone())[0]
        
        await cur.execute("""
            SELECT COUNT(*) FROM messages 
            WHERE sent_at >= CURRENT_DATE
        """)
        messages_today = (await cur.fetchone())[0]
        
        # Сообщения по типам
        await cur.execute("""
            SELECT message_type, COUNT(*) as cnt 
            FROM messages 
            GROUP BY message_type 
            ORDER BY cnt DESC
        """)
        messages_by_type = {row[0]: row[1] for row in await cur.fetchall()}
        
        return Stats(
            total_chats=total_chats,
            total_users=total_users,
            total_messages=total_messages,
            messages_today=messages_today,
            messages_by_type=messages_by_type,
        )


async def get_chats_with_stats() -> List[ChatStats]:
    """Получает список чатов со статистикой."""
    async with get_cursor() as cur:
        await cur.execute("""
            SELECT 
                c.id,
                c.type,
                c.title,
                c.username,
                COUNT(DISTINCT m.message_id) as message_count,
                COUNT(DISTINCT m.user_id) as user_count,
                MAX(m.sent_at) as last_message_at,
                c.first_seen_at
            FROM chats c
            LEFT JOIN messages m ON c.id = m.chat_id
            GROUP BY c.id, c.type, c.title, c.username, c.first_seen_at
            ORDER BY message_count DESC
        """)
        
        rows = await cur.fetchall()
        return [
            ChatStats(
                id=row[0],
                type=row[1],
                title=row[2],
                username=row[3],
                message_count=row[4],
                user_count=row[5],
                last_message_at=row[6],
                first_seen_at=row[7],
            )
            for row in rows
        ]


async def get_chat_by_id(chat_id: int) -> Optional[Dict[str, Any]]:
    """Получает информацию о чате по ID."""
    async with get_cursor() as cur:
        await cur.execute("""
            SELECT id, type, title, username, first_seen_at, last_updated_at
            FROM chats WHERE id = %s
        """, (chat_id,))
        row = await cur.fetchone()
        
        if not row:
            return None
        
        return {
            "id": row[0],
            "type": row[1],
            "title": row[2],
            "username": row[3],
            "first_seen_at": row[4],
            "last_updated_at": row[5],
        }


async def get_users(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """Получает список пользователей."""
    async with get_cursor() as cur:
        await cur.execute("""
            SELECT 
                u.id,
                u.first_name,
                u.last_name,
                u.username,
                u.is_bot,
                u.is_premium,
                u.language_code,
                u.first_seen_at,
                COUNT(m.message_id) as message_count
            FROM users u
            LEFT JOIN messages m ON u.id = m.user_id
            GROUP BY u.id, u.first_name, u.last_name, u.username, 
                     u.is_bot, u.is_premium, u.language_code, u.first_seen_at
            ORDER BY message_count DESC
            LIMIT %s OFFSET %s
        """, (limit, offset))
        
        rows = await cur.fetchall()
        return [
            {
                "id": row[0],
                "first_name": row[1],
                "last_name": row[2],
                "username": row[3],
                "is_bot": row[4],
                "is_premium": row[5],
                "language_code": row[6],
                "first_seen_at": row[7],
                "message_count": row[8],
            }
            for row in rows
        ]


@dataclass
class DashboardChat:
    """Данные чата для дашборда."""
    id: int
    title: Optional[str]
    total_messages: int
    today_messages: int
    last_message_text: Optional[str]
    last_message_author: Optional[str]
    last_message_at: Optional[datetime]
    top_users: List[Dict[str, Any]]


async def get_dashboard_data() -> List[DashboardChat]:
    """Получает данные для дашборда: чаты с полной статистикой."""
    async with get_cursor() as cur:
        # Получаем чаты с базовой статистикой
        await cur.execute("""
            SELECT
                c.id,
                c.title,
                COUNT(m.message_id) as total_messages,
                COUNT(m.message_id) FILTER (WHERE m.sent_at >= CURRENT_DATE) as today_messages
            FROM chats c
            LEFT JOIN messages m ON c.id = m.chat_id
            GROUP BY c.id, c.title
            ORDER BY total_messages DESC
        """)
        chats_data = await cur.fetchall()

        result = []
        for chat_row in chats_data:
            chat_id = chat_row[0]

            # Последнее сообщение
            await cur.execute("""
                SELECT
                    m.text,
                    COALESCE(u.username, u.first_name, 'Unknown') as author,
                    m.sent_at
                FROM messages m
                LEFT JOIN users u ON m.user_id = u.id
                WHERE m.chat_id = %s AND m.text IS NOT NULL
                ORDER BY m.sent_at DESC
                LIMIT 1
            """, (chat_id,))
            last_msg = await cur.fetchone()

            # Топ пользователей за неделю
            await cur.execute("""
                SELECT
                    COALESCE(u.username, u.first_name, 'Unknown') as name,
                    COUNT(*) as count
                FROM messages m
                JOIN users u ON m.user_id = u.id
                WHERE m.chat_id = %s
                  AND m.sent_at >= NOW() - INTERVAL '7 days'
                GROUP BY u.id, u.username, u.first_name
                ORDER BY count DESC
                LIMIT 3
            """, (chat_id,))
            top_users = [{"name": row[0], "count": row[1]} for row in await cur.fetchall()]

            result.append(DashboardChat(
                id=chat_row[0],
                title=chat_row[1],
                total_messages=chat_row[2],
                today_messages=chat_row[3],
                last_message_text=last_msg[0] if last_msg else None,
                last_message_author=last_msg[1] if last_msg else None,
                last_message_at=last_msg[2] if last_msg else None,
                top_users=top_users,
            ))

        return result
