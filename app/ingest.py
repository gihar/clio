"""Приём данных из Telegram: разбор сообщений и запись пользователей/чатов/сообщений."""

import json
from datetime import datetime
from typing import Optional

from telegram import User, Chat, Message, MessageOriginChat, MessageOriginChannel

from .database import get_cursor


def detect_message_type(msg: Message) -> str:
    """Определяет тип сообщения."""
    if msg.text:
        return "text"
    elif msg.photo:
        return "photo"
    elif msg.video:
        return "video"
    elif msg.audio:
        return "audio"
    elif msg.voice:
        return "voice"
    elif msg.video_note:
        return "video_note"
    elif msg.document:
        return "document"
    elif msg.sticker:
        return "sticker"
    elif msg.animation:
        return "animation"
    elif msg.poll:
        return "poll"
    elif msg.location:
        return "location"
    elif msg.contact:
        return "contact"
    elif msg.dice:
        return "dice"
    else:
        return "other"


def get_forward_chat_id(msg: Message) -> Optional[int]:
    """Извлекает ID чата-источника для пересланных сообщений.
    
    В python-telegram-bot v21+ forward_from_chat заменён на forward_origin.
    """
    if not msg.forward_origin:
        return None
    
    # MessageOriginChat - сообщение переслано от имени чата
    if isinstance(msg.forward_origin, MessageOriginChat):
        return msg.forward_origin.sender_chat.id
    
    # MessageOriginChannel - сообщение переслано из канала
    if isinstance(msg.forward_origin, MessageOriginChannel):
        return msg.forward_origin.chat.id
    
    # MessageOriginUser, MessageOriginHiddenUser - нет chat ID
    return None


async def save_user(user: User):
    """Сохраняет или обновляет пользователя."""
    async with get_cursor() as cur:
        await cur.execute("""
            INSERT INTO users (id, is_bot, first_name, last_name, username, language_code, is_premium, last_updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (id) DO UPDATE SET
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                username = EXCLUDED.username,
                language_code = EXCLUDED.language_code,
                is_premium = EXCLUDED.is_premium,
                last_updated_at = NOW();
        """, (
            user.id,
            user.is_bot,
            user.first_name,
            user.last_name,
            user.username,
            user.language_code,
            getattr(user, 'is_premium', False) or False,
        ))


async def save_chat(chat: Chat):
    """Сохраняет или обновляет чат."""
    async with get_cursor() as cur:
        await cur.execute("""
            INSERT INTO chats (id, type, title, username)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                username = EXCLUDED.username,
                last_updated_at = NOW();
        """, (
            chat.id,
            chat.type,
            chat.title,
            chat.username,
        ))


async def record_message(
    *,
    chat_id: int,
    message_id: int,
    user_id: Optional[int],
    sent_at: datetime,
    message_type: str = "text",
    text: Optional[str] = None,
    caption: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
    forward_from_chat_id: Optional[int] = None,
    raw_message: Optional[dict] = None,
) -> None:
    """Записывает сообщение плоскими параметрами (тестопригодный seam, PRD-04).

    Дедупликация по составному ключу (chat_id, message_id): повторный вызов
    с теми же значениями — no-op. НЕ апсертит users/chats — FK-констрейнты
    остаются ответственностью вызывающего.

    Бросает ValueError, если sent_at не передан или message_type — пустая
    строка (программная ошибка вызывающего, тише падать нельзя).
    """
    if sent_at is None:
        raise ValueError("record_message: sent_at is required")
    if not message_type:
        raise ValueError("record_message: message_type must be a non-empty string")

    async with get_cursor() as cur:
        await cur.execute("""
            INSERT INTO messages (
                message_id, chat_id, user_id, message_type, text, caption,
                reply_to_message_id, forward_from_chat_id, sent_at, raw_message
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (chat_id, message_id) DO NOTHING;
        """, (
            message_id,
            chat_id,
            user_id,
            message_type,
            text,
            caption,
            reply_to_message_id,
            forward_from_chat_id,
            sent_at,
            json.dumps(raw_message) if raw_message is not None else None,
        ))


async def record_message_edit(
    *,
    chat_id: int,
    message_id: int,
    edited_at: datetime,
    text: Optional[str] = None,
    caption: Optional[str] = None,
    raw_message: Optional[dict] = None,
) -> None:
    """Обновляет text/caption/edited_at существующего сообщения (PRD-04).

    Тихий no-op, если строка (chat_id, message_id) не найдена — не создаёт
    новую строку.
    """
    async with get_cursor() as cur:
        await cur.execute("""
            UPDATE messages
            SET text = %s, caption = %s, edited_at = %s, raw_message = %s
            WHERE chat_id = %s AND message_id = %s;
        """, (
            text,
            caption,
            edited_at,
            json.dumps(raw_message) if raw_message is not None else None,
            chat_id,
            message_id,
        ))


async def save_message(msg: Message, is_edit: bool = False):
    """Сохраняет сообщение в базу данных.

    Telegram-адаптер поверх record_message/record_message_edit (PRD-04):
    раскладывает telegram.Message в плоские колонки (тип сообщения,
    forward_origin, edit_date) и делегирует запись.
    """
    if not msg.from_user:
        return

    # Сохраняем пользователя и чат
    await save_user(msg.from_user)
    await save_chat(msg.chat)

    text_content = msg.text or None
    caption = msg.caption or None
    raw_message = msg.to_dict()

    if is_edit:
        await record_message_edit(
            chat_id=msg.chat_id,
            message_id=msg.message_id,
            edited_at=msg.edit_date,
            text=text_content,
            caption=caption,
            raw_message=raw_message,
        )
    else:
        reply_to_id = msg.reply_to_message.message_id if msg.reply_to_message else None
        await record_message(
            chat_id=msg.chat_id,
            message_id=msg.message_id,
            user_id=msg.from_user.id,
            sent_at=msg.date,
            message_type=detect_message_type(msg),
            text=text_content,
            caption=caption,
            reply_to_message_id=reply_to_id,
            forward_from_chat_id=get_forward_chat_id(msg),
            raw_message=raw_message,
        )
