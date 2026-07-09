"""Unit-тесты generate_chat_analytics: run_analytics_report с фейковыми
get_chat/fetch/complete (без Postgres/сети, без monkeypatch модульных глобалов).

analytics не идёт через run_report (см. PRD-02 issue #12): LLM опционален
(total==0 -> success без вызова LLM) и отказ LLM не фатален (success остаётся
True). Тем не менее использует тот же CompletionError и общий
log_completion_failure.
"""

from datetime import datetime, timedelta

import pytest

from app.services.analytics import _fill_missing_days, run_analytics_report
from app.services.completion import CompletionError

CHAT = {"id": 1, "title": "Test Chat", "type": "group"}


def _today_str() -> str:
    return datetime.now().date().isoformat()


def _days_ago_str(n: int) -> str:
    return (datetime.now().date() - timedelta(days=n)).isoformat()


async def _fake_get_chat(chat_id):
    return CHAT


async def _fake_get_chat_missing(chat_id):
    return None


def _fetch(daily_counts):
    async def fetch(chat_id, days):
        return daily_counts
    return fetch


async def test_analytics_chat_not_found():
    result = await run_analytics_report(1, get_chat=_fake_get_chat_missing)

    assert result == {"success": False, "error": "Чат не найден"}


async def test_analytics_total_zero_skips_llm_call_entirely():
    complete_calls = []

    async def tracking_complete(prompt, *, system_prompt=None, max_tokens=1000, timeout=30.0):
        complete_calls.append(prompt)
        return "should not be called"

    result = await run_analytics_report(
        1,
        get_chat=_fake_get_chat,
        fetch_daily_counts=_fetch([]),
        complete=tracking_complete,
    )

    assert result["success"] is True
    assert result["ai_comment"] is None
    assert result["error"] is None
    assert result["total"] == 0
    assert complete_calls == []


async def test_analytics_happy_path_with_ai_comment():
    daily_counts = [{"date": "2026-07-08", "count": 5}]

    async def fake_complete(prompt, *, system_prompt=None, max_tokens=1000, timeout=30.0):
        return "Пик активности в понедельник"

    result = await run_analytics_report(
        1,
        get_chat=_fake_get_chat,
        fetch_daily_counts=_fetch(daily_counts),
        complete=fake_complete,
    )

    assert result["success"] is True
    assert result["error"] is None
    assert result["ai_comment"] == "Пик активности в понедельник"
    assert result["total"] == 5
    assert result["chat_type"] == "group"


@pytest.mark.parametrize("kind", ["timeout", "http_error", "not_configured", "bad_response"])
async def test_analytics_llm_failure_is_not_fatal(kind):
    daily_counts = [{"date": "2026-07-08", "count": 5}]

    async def failing_complete(prompt, *, system_prompt=None, max_tokens=1000, timeout=30.0):
        raise CompletionError(kind=kind)

    result = await run_analytics_report(
        1,
        get_chat=_fake_get_chat,
        fetch_daily_counts=_fetch(daily_counts),
        complete=failing_complete,
    )

    assert result["success"] is True
    assert result["ai_comment"] is None
    assert result["error"] == "Не удалось получить AI-комментарий"
    assert result["total"] == 5


def test_fill_missing_days_empty_input_produces_seven_zero_days():
    result = _fill_missing_days([], days=7)

    assert len(result) == 7
    assert all(d["count"] == 0 for d in result)


def test_fill_missing_days_fills_holes_in_the_middle():
    today = _today_str()
    two_days_ago = _days_ago_str(2)

    result = _fill_missing_days(
        [
            {"date": two_days_ago, "count": 3},
            {"date": today, "count": 7},
        ],
        days=3,
    )

    counts_by_date = {d["date"]: d["count"] for d in result}
    assert counts_by_date[two_days_ago] == 3
    assert counts_by_date[today] == 7
    one_day_ago = _days_ago_str(1)
    assert counts_by_date[one_day_ago] == 0
