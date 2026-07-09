"""Сервис аналитики активности чатов.

Не идёт через run_report: LLM опционален (total == 0 → успех без вызова LLM)
и отказ LLM не фатален (success остаётся True). Использует тот же
complete()-seam и describe_completion_error, что и run_report."""

import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..message_reads.digest import get_daily_message_counts
from ..models import get_chat_by_id
from .completion import CompleteFn, CompletionError, describe_completion_error
from .openrouter import complete as openrouter_complete

logger = logging.getLogger(__name__)

ANALYTICS_SYSTEM_PROMPT = """Ты — аналитик активности чата. Даёшь краткие, фактические комментарии по статистике сообщений."""

ANALYTICS_PROMPT_TEMPLATE = """Дай краткий комментарий (2-3 предложения) по статистике сообщений за неделю.

Тип чата: {chat_type}
Период: {date_from} — {date_to}
Данные по дням: {daily_data}
Всего сообщений: {total}
Среднее в день: {average:.1f}

Укажи:
- Где пики и спады активности
- Возможные причины (день недели, выходные и т.д.)

Будь лаконичен, максимум 50 слов."""

LLM_FAILURE_ERROR = "Не удалось получить AI-комментарий"


def _fill_missing_days(daily_counts: List[Dict[str, Any]], days: int = 7) -> List[Dict[str, Any]]:
    """Заполняет пропущенные дни нулями."""
    if not daily_counts:
        # Если нет данных, создаём пустой массив за последние N дней
        result = []
        today = datetime.now().date()
        for i in range(days - 1, -1, -1):
            day = today - timedelta(days=i)
            result.append({"date": day.isoformat(), "count": 0})
        return result

    # Создаём словарь существующих данных
    existing = {item["date"]: item["count"] for item in daily_counts}

    # Определяем диапазон дат
    today = datetime.now().date()
    start_date = today - timedelta(days=days - 1)

    result = []
    current = start_date
    while current <= today:
        date_str = current.isoformat()
        result.append({"date": date_str, "count": existing.get(date_str, 0)})
        current += timedelta(days=1)

    return result


async def run_analytics_report(
    chat_id: int,
    *,
    get_chat: Callable[[int], Awaitable[Optional[Dict[str, Any]]]] = get_chat_by_id,
    fetch_daily_counts: Callable[[int, int], Awaitable[List[Dict[str, Any]]]] = get_daily_message_counts,
    complete: CompleteFn = openrouter_complete,
) -> Dict[str, Any]:
    """Считает аналитику чата за неделю; зависимости — параметры с прод-дефолтами."""
    chat = await get_chat(chat_id)
    if not chat:
        return {"success": False, "error": "Чат не найден"}

    chat_type = chat.get("type", "group")

    daily_counts = await fetch_daily_counts(chat_id, 7)
    daily_messages = _fill_missing_days(daily_counts, days=7)

    total = sum(d["count"] for d in daily_messages)
    average = total / 7 if daily_messages else 0

    if daily_messages:
        date_from = daily_messages[0]["date"]
        date_to = daily_messages[-1]["date"]
        period = f"{date_from} — {date_to}"
    else:
        period = "нет данных"

    base_result = {"success": True, "chat_type": chat_type, "period": period, "daily_messages": daily_messages, "total": total, "average": average}

    # Если нет сообщений, возвращаем без AI-комментария и без вызова LLM.
    if total == 0:
        return {**base_result, "ai_comment": None, "error": None}

    daily_data = ", ".join([f"{d['date']}: {d['count']}" for d in daily_messages])
    prompt = ANALYTICS_PROMPT_TEMPLATE.format(
        chat_type="канал" if chat_type == "channel" else "группа",
        date_from=date_from,
        date_to=date_to,
        daily_data=daily_data,
        total=total,
        average=average,
    )

    try:
        ai_comment = await complete(
            prompt,
            system_prompt=ANALYTICS_SYSTEM_PROMPT,
            max_tokens=150,
            timeout=30.0,
        )
    except CompletionError as e:
        return {**base_result, "ai_comment": None, "error": describe_completion_error(e, LLM_FAILURE_ERROR)}

    return {**base_result, "ai_comment": ai_comment, "error": None}


async def generate_chat_analytics(chat_id: int) -> Dict[str, Any]:
    """Генерирует аналитику чата за последнюю неделю."""
    logger.info(f"Generating analytics for chat {chat_id}")
    return await run_analytics_report(chat_id)
