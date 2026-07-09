"""Фабрика веб-приложения: связывает API-роуты, HTML-страницы и middleware.

Хендлеры живут в api_routes.py (JSON API) и pages.py (Jinja2-страницы);
здесь — только сборка aiohttp.web.Application.
"""

import logging
from pathlib import Path

from aiohttp import web
import aiohttp_jinja2
import jinja2

from .api_routes import (
    health_check,
    api_stats,
    api_chats,
    api_chat_messages,
    api_chat_messages_daily,
    api_chat_messages_export,
    api_chat_join_requests,
    api_dashboard,
    api_chat_summary,
    api_chat_analytics,
    api_chat_strategy,
)
from .pages import dashboard, chats_page, chat_messages_page, users_page

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


@web.middleware
async def cors_middleware(request: web.Request, handler):
    """CORS middleware for API endpoints."""
    # Handle preflight OPTIONS requests
    if request.method == "OPTIONS":
        response = web.Response()
    else:
        try:
            response = await handler(request)
        except web.HTTPException as ex:
            response = ex

    # Add CORS headers (allow all origins)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Max-Age"] = "86400"

    return response


def create_web_app() -> web.Application:
    """Создаёт и настраивает веб-приложение."""
    app = web.Application(middlewares=[cors_middleware])

    # Настройка Jinja2
    aiohttp_jinja2.setup(
        app,
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=jinja2.select_autoescape(['html', 'xml']),
    )

    # Роуты
    app.router.add_get("/health", health_check)
    app.router.add_get("/", dashboard)
    app.router.add_get("/chats", chats_page)
    app.router.add_get("/chats/{chat_id}", chat_messages_page)
    app.router.add_get("/users", users_page)

    # API
    app.router.add_get("/api/stats", api_stats)
    app.router.add_get("/api/chats", api_chats)
    app.router.add_get("/api/chats/{chat_id}/messages", api_chat_messages)
    app.router.add_get("/api/chats/{chat_id}/messages/daily", api_chat_messages_daily)
    app.router.add_get("/api/chats/{chat_id}/messages/export", api_chat_messages_export)
    app.router.add_get("/api/chats/{chat_id}/join-requests", api_chat_join_requests)
    app.router.add_get("/api/dashboard", api_dashboard)
    app.router.add_post("/api/chats/{chat_id}/summary", api_chat_summary)
    app.router.add_get("/api/chats/{chat_id}/analytics", api_chat_analytics)
    app.router.add_post("/api/chats/{chat_id}/strategy", api_chat_strategy)

    # CORS preflight handlers
    app.router.add_route("OPTIONS", "/api/{path:.*}", lambda r: web.Response())

    logger.info("Web application created")
    return app


async def start_web_server(app: web.Application, port: int) -> web.AppRunner:
    """Запускает веб-сервер."""
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web server started on port {port}")
    return runner
