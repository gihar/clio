"""Unit-тесты complete()-seam: openrouter.py как прод-реализация CompleteFn.

Не ходят в сеть и не поднимают Postgres: HTTP замокан через httpx.MockTransport,
конфиг подставляется напрямую через app.config.config.
"""

import httpx
import pytest

import app.config as config_module
from app.config import Config
from app.services.completion import CompletionError, describe_completion_error
from app.services.openrouter import complete


@pytest.fixture(autouse=True)
def _reset_config():
    config_module.config = None
    yield
    config_module.config = None


def _configure(api_key="key-123"):
    config_module.config = Config(
        telegram_token="t",
        database_url="postgresql://x",
        openrouter_api_key=api_key,
    )


async def test_complete_raises_not_configured_without_api_key():
    _configure(api_key=None)

    with pytest.raises(CompletionError) as exc_info:
        await complete("hello")

    assert exc_info.value.kind == "not_configured"


async def test_complete_returns_text_on_success():
    _configure()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "Готовый ответ"}}]})

    result = await complete("hello", transport=httpx.MockTransport(handler))

    assert result == "Готовый ответ"


async def test_complete_raises_timeout_kind():
    _configure()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    with pytest.raises(CompletionError) as exc_info:
        await complete("hello", transport=httpx.MockTransport(handler))

    assert exc_info.value.kind == "timeout"


async def test_complete_raises_http_error_kind():
    _configure()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    with pytest.raises(CompletionError) as exc_info:
        await complete("hello", transport=httpx.MockTransport(handler))

    assert exc_info.value.kind == "http_error"


async def test_complete_raises_bad_response_kind_on_malformed_json():
    _configure()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json at all")

    with pytest.raises(CompletionError) as exc_info:
        await complete("hello", transport=httpx.MockTransport(handler))

    assert exc_info.value.kind == "bad_response"


@pytest.mark.parametrize("kind", ["timeout", "http_error", "not_configured", "bad_response"])
def test_describe_completion_error_returns_caller_message_regardless_of_kind(kind, caplog):
    error = CompletionError(kind=kind)

    result = describe_completion_error(error, "текст для пользователя")

    assert result == "текст для пользователя"
    assert kind in caplog.text


async def test_complete_raises_bad_response_kind_on_missing_choices():
    _configure()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    with pytest.raises(CompletionError) as exc_info:
        await complete("hello", transport=httpx.MockTransport(handler))

    assert exc_info.value.kind == "bad_response"
