"""Единая HTTP-политика API-эндпоинтов админки.

``api_endpoint`` — декоратор, владеющий всей HTTP-политикой JSON API-хендлеров:
маппинг исключений в статусы, guard OpenRouter, маппинг ``{"success": ...}``
в статус, сериализация datetime. Хендлеры сжимаются до «распарсить параметры
-> позвать модуль -> вернуть данные»; специфичная валидация (свои статусы,
свои тела ошибок) остаётся в хендлере — он возвращает ``(data, status)``.

``require_auth`` (routes.py) остаётся отдельным декоратором и всегда ставится
снаружи ``api_endpoint``, чтобы 401 отдавался раньше любой бизнес-логики.
"""

import json
import logging
from datetime import datetime
from functools import wraps
from typing import Any

from aiohttp import web

from ..config import get_config

logger = logging.getLogger(__name__)

OPENROUTER_NOT_CONFIGURED = {"success": False, "error": "OpenRouter API не настроен"}
INVALID_CHAT_ID = {"error": "invalid chat_id"}


def json_response(data: Any, **kwargs) -> web.Response:
    """JSON response с поддержкой кириллицы (``ensure_ascii=False``)."""
    return web.json_response(
        data,
        dumps=lambda x: json.dumps(x, ensure_ascii=False),
        **kwargs,
    )


def _serialize(data: Any) -> Any:
    """Рекурсивно превращает ``datetime`` в ISO-строки; строит новые структуры,
    не мутируя вход (стиль репозитория: immutability)."""
    if isinstance(data, datetime):
        return data.isoformat()
    if isinstance(data, dict):
        return {key: _serialize(value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [_serialize(item) for item in data]
    return data


def api_endpoint(*, requires_llm: bool = False):
    """Декоратор API-хендлера — см. докстринг модуля."""

    def decorator(handler):
        @wraps(handler)
        async def wrapper(request: web.Request) -> web.Response:
            if requires_llm and not get_config().has_openrouter:
                return json_response(OPENROUTER_NOT_CONFIGURED, status=503)

            try:
                result = await handler(request)
            except ValueError:
                return json_response(INVALID_CHAT_ID, status=400)
            except Exception as e:
                logger.error(f"API {handler.__name__} error: {e}")
                return json_response({"error": str(e)}, status=500)

            if isinstance(result, tuple):
                data, status = result
                return json_response(_serialize(data), status=status)

            if isinstance(result, dict) and "success" in result:
                status = 200 if result["success"] else 400
                return json_response(_serialize(result), status=status)

            return json_response(_serialize(result))

        return wrapper

    return decorator
