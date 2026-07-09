"""Unit-тесты api_endpoint: HTTP-политика API-хендлеров без Postgres и без сети.

Хендлеры — голые async-функции, не настоящие aiohttp-роуты; ``request``
передаётся насквозь и в этих тестах не используется хендлерами.
"""

import json
from datetime import datetime

import pytest

import app.config as config_module
from app.config import Config
from app.web.api_wrapper import api_endpoint


def _body(response):
    return json.loads(response.body.decode("utf-8"))


@pytest.fixture(autouse=True)
def _reset_config():
    config_module.config = None
    yield
    config_module.config = None


def _configure(openrouter_api_key=None):
    config_module.config = Config(
        telegram_token="t",
        database_url="postgresql://x",
        openrouter_api_key=openrouter_api_key,
    )


@api_endpoint()
async def _returns_plain_data(request):
    return {"total": 3}


async def test_handler_returning_plain_data_gets_200():
    response = await _returns_plain_data(request=None)

    assert response.status == 200
    assert response.body == b'{"total": 3}'


@api_endpoint()
async def _returns_success_true(request):
    return {"success": True, "summary": "готово"}


async def test_handler_returning_success_true_gets_200():
    response = await _returns_success_true(request=None)

    assert response.status == 200
    assert _body(response) == {"success": True, "summary": "готово"}


@api_endpoint()
async def _returns_success_false(request):
    return {"success": False, "error": "нет сообщений"}


async def test_handler_returning_success_false_gets_400():
    response = await _returns_success_false(request=None)

    assert response.status == 400
    assert _body(response) == {"success": False, "error": "нет сообщений"}


@api_endpoint()
async def _returns_explicit_tuple(request):
    return {"error": "chat not found"}, 404


async def test_handler_returning_tuple_uses_given_status():
    response = await _returns_explicit_tuple(request=None)

    assert response.status == 404
    assert _body(response) == {"error": "chat not found"}


@api_endpoint()
async def _raises_value_error(request):
    raise ValueError("invalid literal for int() with base 10: 'abc'")


async def test_handler_raising_value_error_gets_400_invalid_chat_id():
    response = await _raises_value_error(request=None)

    assert response.status == 400
    assert _body(response) == {"error": "invalid chat_id"}


@api_endpoint()
async def _raises_generic_exception(request):
    raise RuntimeError("boom")


async def test_handler_raising_exception_gets_500_and_logs(caplog):
    response = await _raises_generic_exception(request=None)

    assert response.status == 500
    assert _body(response) == {"error": "boom"}
    assert "_raises_generic_exception" in caplog.text


@api_endpoint(requires_llm=True)
async def _llm_handler(request):
    return {"success": True, "summary": "готово"}


async def test_requires_llm_without_openrouter_key_gets_503_without_calling_handler():
    _configure(openrouter_api_key=None)

    response = await _llm_handler(request=None)

    assert response.status == 503
    assert _body(response) == {"success": False, "error": "OpenRouter API не настроен"}


async def test_requires_llm_with_openrouter_key_calls_handler():
    _configure(openrouter_api_key="key-123")

    response = await _llm_handler(request=None)

    assert response.status == 200
    assert _body(response) == {"success": True, "summary": "готово"}


@api_endpoint()
async def _returns_nested_datetime(request):
    return {
        "sent_at": datetime(2026, 7, 8, 10, 0),
        "messages": [{"edited_at": datetime(2026, 7, 8, 11, 30)}, {"edited_at": None}],
    }


async def test_datetime_is_serialized_recursively_to_isoformat():
    response = await _returns_nested_datetime(request=None)

    assert _body(response) == {
        "sent_at": "2026-07-08T10:00:00",
        "messages": [{"edited_at": "2026-07-08T11:30:00"}, {"edited_at": None}],
    }


async def test_datetime_serialization_does_not_mutate_input():
    original = {"sent_at": datetime(2026, 7, 8, 10, 0)}
    handler_input = dict(original)

    @api_endpoint()
    async def handler(request):
        return handler_input

    await handler(request=None)

    assert handler_input == original
    assert isinstance(handler_input["sent_at"], datetime)
