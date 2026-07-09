"""Сервис генерации саммари по чатам — тонкий вызов run_report со своим spec'ом."""

import functools
import logging
from typing import Any, Callable, Dict, List, Optional

from ..message_reads.digest import get_messages_for_summary
from .reports import ReportSpec, run_report

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — аналитик чатов. Анализируй сообщения из групповых чатов и создавай краткие, информативные саммари на русском языке."""

SUMMARY_PROMPT_TEMPLATE = """Проанализируй сообщения из группового чата за последние сутки.

Чат: {chat_title}
Период: {date_from} — {date_to}
Сообщений: {count}

Сообщения:
{messages}

Дай краткое саммари на русском языке:
1. Основные темы обсуждения (2-3 пункта)
2. Ключевые решения или договорённости (если есть)
3. Важные вопросы без ответа (если есть)

Будь лаконичен, максимум 200 слов."""

EMPTY_ERROR = "Нет сообщений за последние 24 часа"
LLM_FAILURE_ERROR = "Не удалось сгенерировать саммари. Попробуйте позже."


def format_messages_for_prompt(messages: List[Dict[str, Any]]) -> str:
    """Форматирует сообщения для промпта."""
    lines = []
    for msg in messages:
        time_str = msg["sent_at"].strftime("%H:%M")
        author = msg["author"]
        text = msg["text"][:500]  # Ограничиваем длину одного сообщения
        lines.append(f"[{time_str}] @{author}: {text}")
    return "\n".join(lines)


def _build_prompt(chat: Dict[str, Any], messages: List[Dict[str, Any]]):
    date_from = messages[0]["sent_at"]
    date_to = messages[-1]["sent_at"]
    period = f"{date_from.strftime('%d.%m.%Y %H:%M')} — {date_to.strftime('%d.%m.%Y %H:%M')}"

    prompt = SUMMARY_PROMPT_TEMPLATE.format(
        chat_title=chat.get("title") or f"Chat {chat['id']}",
        date_from=date_from.strftime("%d.%m.%Y %H:%M"),
        date_to=date_to.strftime("%d.%m.%Y %H:%M"),
        count=len(messages),
        messages=format_messages_for_prompt(messages),
    )
    return prompt, {"messages_count": len(messages), "period": period}


def _build_result(outcome: str, extra: Optional[Dict[str, Any]] = None, text: Optional[str] = None) -> Dict[str, Any]:
    if outcome == "not_found":
        return {"success": False, "error": "Чат не найден", "summary": None, "messages_count": 0, "period": None}
    if outcome == "empty":
        return {"success": False, "error": EMPTY_ERROR, "summary": None, "messages_count": 0, "period": None}
    if outcome == "llm_failure":
        return {"success": False, "error": LLM_FAILURE_ERROR, "summary": None, **extra}
    return {"success": True, "error": None, "summary": text, **extra}


def build_summary_spec(
    fetch: Optional[Callable] = None,
) -> ReportSpec:
    """Собирает ReportSpec для саммари. ``fetch`` подменяется в тестах."""
    return ReportSpec(
        fetch=fetch or functools.partial(get_messages_for_summary, limit=500),
        build_prompt=_build_prompt,
        system_prompt=SYSTEM_PROMPT,
        max_tokens=500,
        timeout=30.0,
        build_result=_build_result,
    )


async def generate_chat_summary(chat_id: int) -> Dict[str, Any]:
    """Генерирует саммари для чата за последние 24 часа.

    Returns:
        Dict с полями: success, summary, error, messages_count, period
    """
    logger.info(f"Generating summary for chat {chat_id}")
    return await run_report(build_summary_spec(), chat_id)
