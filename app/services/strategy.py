"""Сервис генерации контент-стратегии — тонкий вызов run_report со своим spec'ом."""

import functools
import logging
from typing import Any, Callable, Dict, List, Optional

from ..message_reads.digest import get_messages_for_period
from .reports import ReportSpec, run_report

logger = logging.getLogger(__name__)

STRATEGY_SYSTEM_PROMPT = """Ты — контент-стратег. Анализируешь сообщения из чатов и каналов, даёшь практичные рекомендации по контенту на русском языке."""

STRATEGY_PROMPT_TEMPLATE = """Проанализируй сообщения из {chat_type_ru} за {period_ru}.

Название: {chat_title}
Тип: {chat_type_ru}
Период: {date_range}
Сообщений проанализировано: {count}

Сообщения:
{messages}

Дай отчёт на русском:

## Что зашло
- Какие темы вызвали больше активности/реакций (2-3 пункта)

## Рекомендации
- Что автору стоит делать больше/меньше (2-3 совета)

## Идеи для постов
- 3 конкретные идеи на основе интересов аудитории

Максимум 300 слов."""

INVALID_PERIOD_ERROR = "Неверный период. Используйте 'week' или 'month'"
LLM_FAILURE_ERROR = "Не удалось сгенерировать отчёт. Попробуйте позже."


def format_messages_for_strategy(messages: List[Dict[str, Any]]) -> str:
    """Форматирует сообщения для промпта стратегии."""
    lines = []
    for msg in messages:
        time_str = msg["sent_at"].strftime("%d.%m %H:%M")
        author = msg["author"]
        text = msg["text"][:300] if msg["text"] else ""
        msg_type = msg.get("type", "text")

        if msg_type != "text":
            lines.append(f"[{time_str}] @{author}: [{msg_type}] {text}")
        else:
            lines.append(f"[{time_str}] @{author}: {text}")

    return "\n".join(lines)


def build_strategy_spec(period: str, fetch: Optional[Callable] = None) -> ReportSpec:
    """Собирает ReportSpec для стратегии за ``period`` (уже провалидирован). ``fetch`` подменяется в тестах."""
    days = 7 if period == "week" else 30
    period_ru = "неделю" if period == "week" else "месяц"
    empty_error = f"Нет сообщений за последн{'юю неделю' if period == 'week' else 'ий месяц'}"

    def build_prompt(chat: Dict[str, Any], messages: List[Dict[str, Any]]):
        chat_type = chat.get("type", "group")
        chat_type_ru = "канала" if chat_type == "channel" else "группы"
        chat_title = chat.get("title") or f"Chat {chat['id']}"

        # Сообщения отсортированы по убыванию (новые первые) — переворачиваем
        # для хронологического порядка в промпте.
        date_from = messages[-1]["sent_at"]
        date_to = messages[0]["sent_at"]
        date_range = f"{date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}"

        prompt = STRATEGY_PROMPT_TEMPLATE.format(
            chat_type_ru=chat_type_ru,
            period_ru=period_ru,
            chat_title=chat_title,
            date_range=date_range,
            count=len(messages),
            messages=format_messages_for_strategy(list(reversed(messages))),
        )
        extra = {"chat_type": chat_type, "period": period, "date_range": date_range, "messages_analyzed": len(messages)}
        return prompt, extra

    return ReportSpec(
        fetch=fetch or functools.partial(get_messages_for_period, days=days, limit=500),
        build_prompt=build_prompt,
        system_prompt=STRATEGY_SYSTEM_PROMPT,
        max_tokens=800,
        timeout=45.0,
        not_found_result={"success": False, "error": "Чат не найден"},
        empty_result={"success": False, "error": empty_error},
        llm_failure_message=LLM_FAILURE_ERROR,
        build_failure=lambda extra, message: {"success": False, "error": message, **extra},
        build_success=lambda extra, text: {"success": True, "error": None, "report": text, **extra},
    )


async def generate_content_strategy(chat_id: int, period: str = "week") -> Dict[str, Any]:
    """Генерирует контент-стратегию для чата. ``period``: "week" (7 дней) или "month" (30 дней)."""
    if period not in ("week", "month"):
        return {"success": False, "error": INVALID_PERIOD_ERROR}

    logger.info(f"Generating strategy for chat {chat_id}, period={period}")
    return await run_report(build_strategy_spec(period), chat_id)
