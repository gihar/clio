"""Клиент для OpenRouter API — прод-реализация complete()-seam (см. completion.py).

Единственное место, которое знает про HTTP, заголовки, payload и
``OPENROUTER_API_URL``. Конфиг читается внутри адаптера (см. PRD-02 FR-6).
"""

import logging
from typing import Optional

import httpx

from ..config import get_config
from .completion import CompletionError

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


async def complete(
    prompt: str,
    *,
    system_prompt: Optional[str] = None,
    max_tokens: int = 1000,
    timeout: float = 30.0,
    transport: Optional[httpx.BaseTransport] = None,
) -> str:
    """Генерирует ответ через OpenRouter API.

    ``transport`` — тестовый seam для httpx.MockTransport, в проде не передаётся.
    Raises CompletionError(kind=...) вместо возврата None: not_configured,
    timeout, http_error или bad_response.
    """
    config = get_config()

    if not config.has_openrouter:
        logger.warning("OpenRouter API key not configured")
        raise CompletionError(kind="not_configured")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    headers = {
        "Authorization": f"Bearer {config.openrouter_api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": config.openrouter_model,
        "messages": messages,
        "max_tokens": max_tokens,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.post(
                OPENROUTER_API_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            logger.info(f"OpenRouter response received, {len(content)} chars")
            return content

    except httpx.TimeoutException as e:
        logger.error("OpenRouter request timed out")
        raise CompletionError(kind="timeout") from e
    except httpx.HTTPStatusError as e:
        logger.error(f"OpenRouter HTTP error: {e.response.status_code}")
        raise CompletionError(kind="http_error") from e
    except CompletionError:
        raise
    except Exception as e:
        logger.error(f"OpenRouter error: {e}")
        raise CompletionError(kind="bad_response") from e
