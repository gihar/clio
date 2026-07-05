"""Чистая логика: классификация изменения статуса участника как спам-сигнала.

Без I/O — только правила. Хендлер вытаскивает поля из ``ChatMemberUpdated``
и вызывает эти функции.
"""

from datetime import datetime
from typing import Optional


def _is_indefinite(until_date: Optional[datetime]) -> bool:
    """Ограничение бессрочно?

    ``until_date is None`` — очевидный случай. Но python-telegram-bot кодирует
    сентинел Bot API «навсегда» (``until_date=0``) как эпоху 1970 (timestamp 0),
    а не None — поэтому любой ``timestamp() <= 0`` тоже считаем бессрочным.
    Реальный временный мут всегда в будущем (timestamp сильно > 0).
    """
    return until_date is None or until_date.timestamp() <= 0


def is_spam_mute(
    new_status: str,
    new_can_send_messages: Optional[bool],
    new_until_date: Optional[datetime],
) -> bool:
    """True, если новое состояние участника — полный бессрочный мут.

    Полный бессрочный мут (антиспам-бот снял все права писать, без срока) —
    наш сигнал «это был спамер». Принимает ``until_date`` прямо из PTB
    (нормализация сентинела «навсегда» — внутри).
    """
    return (
        new_status == "restricted"
        and new_can_send_messages is False
        and _is_indefinite(new_until_date)
    )
