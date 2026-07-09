"""Единый пайплайн LLM-отчётов: fetch → guard → prompt → complete → result.

summary.py/strategy.py собирают свой ``ReportSpec`` и вызывают ``run_report`` —
конвейер реализован здесь один раз. ``get_chat``/``complete`` — параметры с
прод-дефолтами (FR-5): тесты подставляют фейки, не трогая модульные глобалы.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..models import get_chat_by_id
from .completion import CompleteFn, CompletionError, describe_completion_error
from .openrouter import complete as openrouter_complete


@dataclass(frozen=True)
class ReportSpec:
    """Параметры одного вида отчёта. ``not_found_result``/``empty_result`` — готовые
    dict'и; ``llm_failure_message`` — report-специфичный текст отказа LLM (не
    зависит от kind); ``build_failure``/``build_success`` строят результат из
    ``extra`` (доп. поля, вторая часть кортежа ``build_prompt``) и текста (сообщения
    об отказе или ответа LLM)."""

    fetch: Callable[[int], Awaitable[List[Dict[str, Any]]]]
    build_prompt: Callable[[Dict[str, Any], List[Dict[str, Any]]], tuple]
    system_prompt: str
    max_tokens: int
    timeout: float
    not_found_result: Dict[str, Any]
    empty_result: Dict[str, Any]
    llm_failure_message: str
    build_failure: Callable[[Dict[str, Any], str], Dict[str, Any]]
    build_success: Callable[[Dict[str, Any], str], Dict[str, Any]]


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
        return dict(spec.not_found_result)

    messages = await spec.fetch(chat_id)
    if not messages:
        return dict(spec.empty_result)

    prompt, extra = spec.build_prompt(chat, messages)

    try:
        text = await complete(
            prompt,
            system_prompt=spec.system_prompt,
            max_tokens=spec.max_tokens,
            timeout=spec.timeout,
        )
    except CompletionError as e:
        return spec.build_failure(extra, describe_completion_error(e, spec.llm_failure_message))

    return spec.build_success(extra, text)
