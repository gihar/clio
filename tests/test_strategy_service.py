"""Unit-тесты generate_content_strategy: реальный ReportSpec стратегии через
run_report с фейковыми get_chat/fetch/complete (без Postgres/сети)."""

from datetime import datetime

import pytest

from app.services.completion import CompletionError
from app.services.reports import run_report
from app.services.strategy import (
    build_strategy_spec,
    format_messages_for_strategy,
    generate_content_strategy,
)

CHAT = {"id": 1, "title": "Vibe Chat", "type": "group"}

# Фетчер отдаёт DESC (новые первые) — как реальный get_messages_for_period.
MESSAGES_DESC = [
    {"text": "Второе", "author": "bob", "sent_at": datetime(2026, 7, 8, 11, 0), "type": "text"},
    {"text": "Первое", "author": "alice", "sent_at": datetime(2026, 7, 1, 9, 0), "type": "text"},
]


async def _fake_get_chat(chat_id):
    return CHAT


async def _fake_get_chat_missing(chat_id):
    return None


def _fetch(messages):
    async def fetch(chat_id):
        return messages
    return fetch


async def _complete_success(prompt, *, system_prompt=None, max_tokens=1000, timeout=30.0):
    return "Готовый отчёт"


async def test_strategy_happy_path():
    spec = build_strategy_spec("week", fetch=_fetch(MESSAGES_DESC))

    result = await run_report(spec, chat_id=1, get_chat=_fake_get_chat, complete=_complete_success)

    assert result == {
        "success": True,
        "error": None,
        "chat_type": "group",
        "period": "week",
        "date_range": "01.07.2026 — 08.07.2026",
        "messages_analyzed": 2,
        "report": "Готовый отчёт",
    }


async def test_strategy_invalid_period_rejected_without_pipeline():
    result = await generate_content_strategy(1, period="year")

    assert result == {
        "success": False,
        "error": "Неверный период. Используйте 'week' или 'month'",
    }


async def test_strategy_chat_not_found():
    spec = build_strategy_spec("week", fetch=_fetch(MESSAGES_DESC))

    result = await run_report(spec, chat_id=1, get_chat=_fake_get_chat_missing, complete=_complete_success)

    assert result == {"success": False, "error": "Чат не найден"}


@pytest.mark.parametrize(
    "period,expected_error",
    [
        ("week", "Нет сообщений за последнюю неделю"),
        ("month", "Нет сообщений за последний месяц"),
    ],
)
async def test_strategy_no_messages(period, expected_error):
    spec = build_strategy_spec(period, fetch=_fetch([]))

    result = await run_report(spec, chat_id=1, get_chat=_fake_get_chat, complete=_complete_success)

    assert result == {"success": False, "error": expected_error}


@pytest.mark.parametrize("kind", ["timeout", "http_error", "not_configured", "bad_response"])
async def test_strategy_llm_failure_any_kind_has_no_report_key(kind):
    async def failing_complete(prompt, *, system_prompt=None, max_tokens=1000, timeout=30.0):
        raise CompletionError(kind=kind)

    spec = build_strategy_spec("week", fetch=_fetch(MESSAGES_DESC))

    result = await run_report(spec, chat_id=1, get_chat=_fake_get_chat, complete=failing_complete)

    assert result == {
        "success": False,
        "error": "Не удалось сгенерировать отчёт. Попробуйте позже.",
        "chat_type": "group",
        "period": "week",
        "date_range": "01.07.2026 — 08.07.2026",
        "messages_analyzed": 2,
    }
    assert "report" not in result


def test_format_messages_for_strategy_truncates_to_300_chars():
    long_text = "y" * 400
    messages = [{"text": long_text, "author": "alice", "sent_at": datetime(2026, 7, 8, 10, 0), "type": "text"}]

    formatted = format_messages_for_strategy(messages)

    assert formatted == f"[08.07 10:00] @alice: {'y' * 300}"


def test_build_prompt_reverses_desc_order_to_chronological():
    spec = build_strategy_spec("week", fetch=_fetch(MESSAGES_DESC))
    prompt, _extra = spec.build_prompt(CHAT, MESSAGES_DESC)

    first_index = prompt.index("Первое")
    second_index = prompt.index("Второе")
    assert first_index < second_index
