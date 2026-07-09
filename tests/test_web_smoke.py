"""T-2 из PRD-05: smoke-тесты веб-слоя через aiohttp test client.

pytest-aiohttp не установлен — TestServer/TestClient поднимаются вручную под
pytest-asyncio (asyncio_mode=auto). Модули данных подменяются фейками через
monkeypatch модульных ссылок в app.web.api_routes — Postgres не нужен.
"""

import base64

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

import app.config as config_module
from app.config import Config
from app.web import api_routes
from app.web.routes import create_web_app


@pytest_asyncio.fixture(autouse=True)
async def _reset_config():
    config_module.config = None
    yield
    config_module.config = None


def _configure(**overrides):
    defaults = dict(telegram_token="t", database_url="postgresql://x")
    defaults.update(overrides)
    config_module.config = Config(**defaults)


@pytest_asyncio.fixture
async def client():
    server = TestServer(create_web_app())
    async with TestClient(server) as c:
        yield c


class _FakeStats:
    total_chats = 3
    total_users = 10
    total_messages = 500
    messages_today = 12
    messages_by_type = {"text": 480, "photo": 20}


async def test_api_stats_happy_path(client, monkeypatch):
    _configure()

    async def fake_get_stats():
        return _FakeStats()

    monkeypatch.setattr(api_routes, "get_stats", fake_get_stats)

    response = await client.get("/api/stats")

    assert response.status == 200
    assert await response.json() == {
        "total_chats": 3,
        "total_users": 10,
        "total_messages": 500,
        "messages_today": 12,
        "messages_by_type": {"text": 480, "photo": 20},
    }


async def test_api_stats_requires_auth_when_configured(client, monkeypatch):
    _configure(admin_username="admin", admin_password="secret")

    async def fake_get_stats():
        return _FakeStats()

    monkeypatch.setattr(api_routes, "get_stats", fake_get_stats)

    unauthenticated = await client.get("/api/stats")
    assert unauthenticated.status == 401

    creds = base64.b64encode(b"admin:secret").decode()
    authenticated = await client.get("/api/stats", headers={"Authorization": f"Basic {creds}"})
    assert authenticated.status == 200


async def test_api_chat_summary_happy_path(client, monkeypatch):
    _configure(openrouter_api_key="key-123")

    async def fake_generate_chat_summary(chat_id):
        return {
            "success": True,
            "error": None,
            "summary": "Готовое саммари",
            "messages_count": 2,
            "period": "08.07.2026 10:00 — 08.07.2026 11:30",
        }

    monkeypatch.setattr(api_routes, "generate_chat_summary", fake_generate_chat_summary)

    response = await client.post("/api/chats/1/summary")

    assert response.status == 200
    body = await response.json()
    assert body["success"] is True
    assert body["summary"] == "Готовое саммари"


async def test_api_chat_summary_without_openrouter_returns_503(client, monkeypatch):
    _configure(openrouter_api_key=None)

    async def fail_if_called(chat_id):
        raise AssertionError("generate_chat_summary must not be called without OpenRouter")

    monkeypatch.setattr(api_routes, "generate_chat_summary", fail_if_called)

    response = await client.post("/api/chats/1/summary")

    assert response.status == 503
    assert await response.json() == {
        "success": False,
        "error": "OpenRouter API не настроен",
    }
