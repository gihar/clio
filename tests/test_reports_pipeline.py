"""Unit-тесты run_report: механика конвейера (fetch → guard → complete → result)
на синтетическом ReportSpec, независимо от конкретных отчётов.

Никакого Postgres/сети: get_chat/fetch/complete — фейки, подставленные как
параметры (FR-5), без monkeypatch модульных глобалов.
"""

import pytest

from app.services.completion import CompletionError
from app.services.reports import ReportSpec, run_report

CHAT = {"id": 1, "title": "Test Chat"}
MESSAGES = [{"text": "hi"}]


def _spec(**overrides) -> ReportSpec:
    defaults = dict(
        fetch=lambda chat_id: _async_return(MESSAGES),
        build_prompt=lambda chat, messages: ("prompt text", {"count": len(messages)}),
        system_prompt="system",
        max_tokens=100,
        timeout=10.0,
        not_found_result={"outcome": "not_found", "extra": None, "text": None},
        empty_result={"outcome": "empty", "extra": None, "text": None},
        build_failure=lambda extra: {"outcome": "llm_failure", "extra": extra, "text": None},
        build_success=lambda extra, text: {"outcome": "success", "extra": extra, "text": text},
    )
    defaults.update(overrides)
    return ReportSpec(**defaults)


async def _async_return(value):
    return value


async def _fake_get_chat_found(chat_id):
    return CHAT


async def _fake_get_chat_missing(chat_id):
    return None


async def _fake_complete_success(prompt, *, system_prompt=None, max_tokens=1000, timeout=30.0):
    return "llm text"


async def test_run_report_returns_not_found_result_when_chat_missing():
    result = await run_report(_spec(), chat_id=1, get_chat=_fake_get_chat_missing, complete=_fake_complete_success)

    assert result == {"outcome": "not_found", "extra": None, "text": None}


async def test_run_report_returns_empty_result_when_no_messages():
    spec = _spec(fetch=lambda chat_id: _async_return([]))

    result = await run_report(spec, chat_id=1, get_chat=_fake_get_chat_found, complete=_fake_complete_success)

    assert result == {"outcome": "empty", "extra": None, "text": None}


async def test_run_report_returns_success_result_with_llm_text():
    result = await run_report(_spec(), chat_id=1, get_chat=_fake_get_chat_found, complete=_fake_complete_success)

    assert result == {"outcome": "success", "extra": {"count": 1}, "text": "llm text"}


@pytest.mark.parametrize("kind", ["timeout", "http_error", "not_configured", "bad_response"])
async def test_run_report_maps_any_completion_error_kind_to_llm_failure(kind):
    async def failing_complete(prompt, *, system_prompt=None, max_tokens=1000, timeout=30.0):
        raise CompletionError(kind=kind)

    result = await run_report(_spec(), chat_id=1, get_chat=_fake_get_chat_found, complete=failing_complete)

    assert result == {"outcome": "llm_failure", "extra": {"count": 1}, "text": None}


async def test_run_report_does_not_fetch_messages_when_chat_not_found():
    fetch_calls = []

    async def tracking_fetch(chat_id):
        fetch_calls.append(chat_id)
        return MESSAGES

    spec = _spec(fetch=tracking_fetch)

    await run_report(spec, chat_id=1, get_chat=_fake_get_chat_missing, complete=_fake_complete_success)

    assert fetch_calls == []
