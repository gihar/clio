"""HTML-страницы админки (Jinja2)."""

import logging

from aiohttp import web
import aiohttp_jinja2

from ..config import get_config
from ..models import get_chat_by_id, get_chats_with_stats, get_dashboard_data, get_users
from ..message_reads.raw import get_chat_messages
from .auth import require_auth

logger = logging.getLogger(__name__)


@require_auth
@aiohttp_jinja2.template("dashboard.html")
async def dashboard(request: web.Request):
    """Главная страница дашборда."""
    chats = await get_dashboard_data()

    return {
        "request": request,
        "chats": chats,
    }


@require_auth
@aiohttp_jinja2.template("chats.html")
async def chats_page(request: web.Request):
    """Страница списка чатов."""
    chats = await get_chats_with_stats()
    return {"request": request, "chats": chats}


@require_auth
@aiohttp_jinja2.template("messages.html")
async def chat_messages_page(request: web.Request):
    """Страница сообщений чата."""
    chat_id = int(request.match_info["chat_id"])
    page = int(request.query.get("page", 1))
    message_type = request.query.get("type")
    limit = 50
    offset = (page - 1) * limit

    chat = await get_chat_by_id(chat_id)
    if not chat:
        raise web.HTTPNotFound(text="Chat not found")

    messages = await get_chat_messages(chat_id, limit, offset, message_type)

    config = get_config()
    is_vibecoder = False
    if chat:
        title = (chat.get("title") or "").lower()
        is_vibecoder = (
            (config.vibecoder_chat_id == chat_id)
            or ("вайбкод" in title)
        )

    return {
        "request": request,
        "chat": chat,
        "messages": messages,
        "page": page,
        "message_type": message_type,
        "has_next": len(messages) == limit,
        "has_prev": page > 1,
        "is_vibecoder": is_vibecoder,
    }


@require_auth
@aiohttp_jinja2.template("users.html")
async def users_page(request: web.Request):
    """Страница списка пользователей."""
    page = int(request.query.get("page", 1))
    limit = 50
    offset = (page - 1) * limit

    users = await get_users(limit, offset)

    return {
        "request": request,
        "users": users,
        "page": page,
        "has_next": len(users) == limit,
        "has_prev": page > 1,
    }
