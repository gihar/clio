"""Базовая авторизация админки."""

import base64
from functools import wraps

from aiohttp import web

from ..config import get_config


def check_auth(request: web.Request) -> bool:
    """Проверяет базовую авторизацию."""
    config = get_config()

    if not config.has_auth:
        return True  # Авторизация не настроена

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        return False

    try:
        encoded = auth_header[6:]
        decoded = base64.b64decode(encoded).decode("utf-8")
        username, password = decoded.split(":", 1)
        return username == config.admin_username and password == config.admin_password
    except Exception:
        return False


def require_auth(handler):
    """Декоратор для проверки авторизации."""
    @wraps(handler)
    async def wrapper(request: web.Request):
        if not check_auth(request):
            return web.Response(
                status=401,
                headers={"WWW-Authenticate": 'Basic realm="Admin Panel"'},
                text="Unauthorized"
            )
        return await handler(request)
    return wrapper
