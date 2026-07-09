"""Unit-тесты generate_chat_summary: реальный ReportSpec саммари через run_report
с фейковыми get_chat/fetch/complete (без Postgres/сети, без monkeypatch глобалов).
"""

from datetime import datetime

import pytest

from app.services.completion import CompletionError
from app.services.reports import run_report
from app.services.summary import build_summary_spec, format_messages_for_prompt

CHAT = {"id": 1, "title": "Vibe Chat", "type": "group"}

MESSAGES = [
    {"text": "Привет", "author": "alice", "sent_at": datetime(2026, 7, 8, 10, 0)},
    {"text": "Как дела?", "author": "bob", "sent_at": datetime(2026, 7, 8, 11, 30)},
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
    return "Готовое саммари"


async def test_summary_happy_path():
    spec = build_summary_spec(fetch=_fetch(MESSAGES))

    result = await run_report(spec, chat_id=1, get_chat=_fake_get_chat, complete=_complete_success)

    assert result == {
        "success": True,
        "error": None,
        "summary": "Готовое саммари",
        "messages_count": 2,
        "period": "08.07.2026 10:00 — 08.07.2026 11:30",
    }


async def test_summary_chat_not_found():
    spec = build_summary_spec(fetch=_fetch(MESSAGES))

    result = await run_report(spec, chat_id=1, get_chat=_fake_get_chat_missing, complete=_complete_success)

    assert result == {
        "success": False,
        "error": "Чат не найден",
        "summary": None,
        "messages_count": 0,
        "period": None,
    }


async def test_summary_no_messages():
    spec = build_summary_spec(fetch=_fetch([]))

    result = await run_report(spec, chat_id=1, get_chat=_fake_get_chat, complete=_complete_success)

    assert result == {
        "success": False,
        "error": "Нет сообщений за последние 24 часа",
        "summary": None,
        "messages_count": 0,
        "period": None,
    }


@pytest.mark.parametrize("kind", ["timeout", "http_error", "not_configured", "bad_response"])
async def test_summary_llm_failure_any_kind(kind):
    async def failing_complete(prompt, *, system_prompt=None, max_tokens=1000, timeout=30.0):
        raise CompletionError(kind=kind)

    spec = build_summary_spec(fetch=_fetch(MESSAGES))

    result = await run_report(spec, chat_id=1, get_chat=_fake_get_chat, complete=failing_complete)

    assert result == {
        "success": False,
        "error": "Не удалось сгенерировать саммари. Попробуйте позже.",
        "summary": None,
        "messages_count": 2,
        "period": "08.07.2026 10:00 — 08.07.2026 11:30",
    }


def test_format_messages_for_prompt_truncates_to_500_chars():
    long_text = "x" * 600
    messages = [{"text": long_text, "author": "alice", "sent_at": datetime(2026, 7, 8, 10, 0)}]

    formatted = format_messages_for_prompt(messages)

    assert formatted == f"[10:00] @alice: {'x' * 500}"
