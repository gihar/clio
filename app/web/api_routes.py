"""JSON API-хендлеры админки. HTTP-политика — в api_wrapper.api_endpoint;
специфичная валидация (свои статусы/тела) остаётся здесь, в хендлерах."""

import logging
from datetime import datetime

from aiohttp import web

from ..config import get_config
from ..database import ping
from ..admin_reads import (
    get_stats,
    get_chats_with_stats,
    get_chat_by_id,
    get_dashboard_data,
)
from ..join_request_status import JoinRequestStatus
from ..join_requests import get_join_requests
from ..message_reads.raw import (
    get_chat_messages,
    get_chat_messages_by_date,
    get_chat_messages_by_date_range,
)
from ..services.summary import generate_chat_summary
from ..services.analytics import generate_chat_analytics
from ..services.strategy import generate_content_strategy
from .api_wrapper import api_endpoint, json_response
from .auth import require_auth

logger = logging.getLogger(__name__)


# ========== Health Check ==========

async def health_check(request: web.Request) -> web.Response:
    """Health check endpoint для Railway."""
    if await ping():
        return json_response({
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })

    return json_response({
        "status": "unhealthy",
        "database": "disconnected",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }, status=500)


# ========== API ==========

@require_auth
@api_endpoint()
async def api_stats(request: web.Request):
    """API: общая статистика."""
    stats = await get_stats()
    return {
        "total_chats": stats.total_chats,
        "total_users": stats.total_users,
        "total_messages": stats.total_messages,
        "messages_today": stats.messages_today,
        "messages_by_type": stats.messages_by_type,
    }


@require_auth
@api_endpoint()
async def api_chats(request: web.Request):
    """API: список чатов."""
    chats = await get_chats_with_stats()
    return [
        {
            "id": c.id,
            "type": c.type,
            "title": c.title,
            "username": c.username,
            "message_count": c.message_count,
            "user_count": c.user_count,
            "last_message_at": c.last_message_at,
        }
        for c in chats
    ]


@require_auth
@api_endpoint()
async def api_chat_messages(request: web.Request):
    """API: сообщения чата."""
    chat_id = int(request.match_info["chat_id"])
    limit = int(request.query.get("limit", 100))
    offset = int(request.query.get("offset", 0))
    message_type = request.query.get("type")

    return await get_chat_messages(chat_id, limit, offset, message_type)


@require_auth
@api_endpoint()
async def api_chat_messages_daily(request: web.Request):
    """API: сообщения чата за конкретный день (UTC+3)."""
    chat_id = int(request.match_info["chat_id"])
    date_str = request.query.get("date")  # format: YYYY-MM-DD

    if not date_str:
        return {"error": "date parameter required (YYYY-MM-DD)"}, 400

    messages = await get_chat_messages_by_date(chat_id, date_str)

    return {
        "chat_id": chat_id,
        "date": date_str,
        "timezone": "UTC+3",
        "count": len(messages),
        "messages": messages,
    }


@require_auth
@api_endpoint()
async def api_chat_messages_export(request: web.Request):
    """API: экспорт сообщений чата за диапазон дат (UTC+3)."""
    chat_id = int(request.match_info["chat_id"])
    date_from = request.query.get("from")
    date_to = request.query.get("to")

    if not date_from or not date_to:
        return {"error": "from and to parameters required (YYYY-MM-DD)"}, 400

    # Validate date format
    try:
        datetime.strptime(date_from, "%Y-%m-%d")
        datetime.strptime(date_to, "%Y-%m-%d")
    except ValueError:
        return {"error": "invalid date format, use YYYY-MM-DD"}, 400

    # Validate range
    if date_from > date_to:
        return {"error": "from date must be before or equal to to date"}, 400

    # Get chat info
    chat = await get_chat_by_id(chat_id)
    if not chat:
        return {"error": "chat not found"}, 404

    messages = await get_chat_messages_by_date_range(chat_id, date_from, date_to)

    return {
        "chat_id": chat_id,
        "chat_title": chat.get("title"),
        "period": {
            "from": date_from,
            "to": date_to,
        },
        "timezone": "UTC+3",
        "messages_count": len(messages),
        "messages": messages,
    }


@require_auth
@api_endpoint()
async def api_dashboard(request: web.Request):
    """API: данные для дашборда."""
    chats = await get_dashboard_data()
    config = get_config()

    return {
        "chats": [
            {
                "id": c.id,
                "title": c.title or f"Chat {c.id}",
                "total_messages": c.total_messages,
                "today_messages": c.today_messages,
                "last_message": {
                    "text": c.last_message_text[:100] if c.last_message_text else None,
                    "author": c.last_message_author,
                    "sent_at": c.last_message_at,
                } if c.last_message_text else None,
                "top_users_week": c.top_users,
            }
            for c in chats
        ],
        "has_openrouter": config.has_openrouter,
    }


@require_auth
@api_endpoint(requires_llm=True)
async def api_chat_summary(request: web.Request):
    """API: генерация саммари для чата."""
    chat_id = int(request.match_info["chat_id"])
    return await generate_chat_summary(chat_id)


@require_auth
@api_endpoint(requires_llm=True)
async def api_chat_analytics(request: web.Request):
    """API: аналитика чата за неделю."""
    chat_id = int(request.match_info["chat_id"])
    return await generate_chat_analytics(chat_id)


@require_auth
@api_endpoint(requires_llm=True)
async def api_chat_strategy(request: web.Request):
    """API: генерация контент-стратегии для чата."""
    chat_id = int(request.match_info["chat_id"])

    # Получаем период из тела запроса
    try:
        body = await request.json()
        period = body.get("period", "week")
    except Exception:
        period = "week"

    return await generate_content_strategy(chat_id, period=period)


@require_auth
@api_endpoint()
async def api_chat_join_requests(request: web.Request):
    """API: join requests for a chat (pending/declined/expired)."""
    chat_id = int(request.match_info["chat_id"])
    limit = int(request.query.get("limit", 100))
    offset = int(request.query.get("offset", 0))
    status = request.query.get("status")

    if status and status not in JoinRequestStatus:
        return {"error": "invalid status"}, 400

    reqs = await get_join_requests(chat_id, limit=limit, offset=offset, status=status)

    return {
        "chat_id": chat_id,
        "status": status,
        "count": len(reqs),
        "requests": reqs,
    }
