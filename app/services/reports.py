"""Единый пайплайн LLM-отчётов: fetch → guard → prompt → complete → result.

summary.py и strategy.py собирают свой ``ReportSpec`` (параметры конвейера)
и вызывают ``run_report`` — весь конвейер реализован здесь ровно один раз.
Зависимости (``get_chat``, ``complete``) — параметры с прод-дефолтами (FR-5):
тесты подставляют фейки, не трогая модульные глобалы.
"""

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..models import get_chat_by_id
from .completion import CompleteFn, CompletionError
from .openrouter import complete as openrouter_complete

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReportSpec:
    """Параметры одного вида отчёта (summary/strategy/...).

    ``fetch`` получает данные по ``chat_id``; ``build_prompt`` превращает
    (chat, данные) в (промпт, доп. поля результата); ``build_result`` собирает
    итоговый dict для каждого исхода конвейера:
    outcome ∈ {"not_found", "empty", "llm_failure", "success"}.
    """

    fetch: Callable[[int], Awaitable[List[Dict[str, Any]]]]
    build_prompt: Callable[[Dict[str, Any], List[Dict[str, Any]]], tuple]
    system_prompt: str
    max_tokens: int
    timeout: float
    build_result: Callable[..., Dict[str, Any]]


async def run_report(
    spec: ReportSpec,
    chat_id: int,
    *,
    get_chat: Callable[[int], Awaitable[Optional[Dict[str, Any]]]] = get_chat_by_id,
    complete: CompleteFn = openrouter_complete,
) -> Dict[str, Any]:
    """Прогоняет chat_id через конвейер ``spec`` и возвращает итоговый dict."""
    chat = await get_chat(chat_id)
    if chat is None:
        return spec.build_result("not_found")

    messages = await spec.fetch(chat_id)
    if not messages:
        return spec.build_result("empty")

    prompt, extra = spec.build_prompt(chat, messages)

    try:
        text = await complete(
            prompt,
            system_prompt=spec.system_prompt,
            max_tokens=spec.max_tokens,
            timeout=spec.timeout,
        )
    except CompletionError as e:
        logger.error(f"LLM completion failed (kind={e.kind})")
        return spec.build_result("llm_failure", extra=extra)

    return spec.build_result("success", extra=extra, text=text)
