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


def log_completion_failure(error: CompletionError) -> None:
    """Единственное место, логирующее отказ complete() — общее для run_report
    (LLM обязателен) и вызывающих, где отказ не фатален (analytics)."""
    logger.error(f"LLM completion failed (kind={error.kind})")
