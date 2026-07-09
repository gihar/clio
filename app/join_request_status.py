"""Единый словарь статусов join-заявок (PRD-06).

Единственное место, где перечисляются допустимые значения `join_requests.status`.
Схема (`app/schema.py`), веб-валидация (`app/web/api_routes.py`) и бот-хендлер
(`app/bot/handlers.py`) ссылаются на этот enum вместо голых строк.
"""

from enum import StrEnum


class JoinRequestStatus(StrEnum):
    """Статус заявки на вступление в чат."""

    PENDING = "pending"
    DECLINED = "declined"
    EXPIRED = "expired"
