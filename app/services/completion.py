"""Seam LLM-вызова: типизированные отказы вместо схлопывания в None.

``complete()`` (см. прод-реализацию в ``openrouter.py``) либо возвращает текст,
либо бросает :class:`CompletionError` — единственный способ узнать об отказе.
"""

from typing import Optional, Protocol


class CompletionError(Exception):
    """Отказ LLM-вызова с машиночитаемым видом ошибки.

    ``kind`` — один из: ``not_configured``, ``timeout``, ``http_error``,
    ``bad_response``.
    """

    def __init__(self, kind: str, message: str = ""):
        self.kind = kind
        super().__init__(message or kind)


class CompleteFn(Protocol):
    """Форма адаптера LLM-вызова, инжектируемого в пайплайн отчётов."""

    async def __call__(
        self,
        prompt: str,
        *,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000,
        timeout: float = 30.0,
    ) -> str:
        ...
