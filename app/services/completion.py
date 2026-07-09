"""Seam LLM-вызова: complete() бросает CompletionError вместо возврата None."""

import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# Форма адаптера LLM-вызова, инжектируемого в пайплайн отчётов (прод-реализация
# — openrouter.complete). kind ∈ {not_configured, timeout, http_error, bad_response}.
CompleteFn = Callable[..., Awaitable[str]]


class CompletionError(Exception):
    """Отказ LLM-вызова с машиночитаемым ``kind``."""

    def __init__(self, kind: str, message: str = ""):
        self.kind = kind
        super().__init__(message or kind)


def describe_completion_error(error: CompletionError, message: str) -> str:
    """Единственное место конвертации CompletionError в текст для результата.

    ``kind`` уходит в лог (для диагностики); пользователю — ``message``,
    переданный report-специфично вызывающим (тексты сегодня не зависят от
    ``kind``, как и раньше). Общее для run_report и analytics.
    """
    logger.error(f"LLM completion failed (kind={error.kind}): {error}")
    return message
