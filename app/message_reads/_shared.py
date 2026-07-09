"""Приватные строительные блоки, общие для digest.py и raw.py.

Не публичный интерфейс пакета — вызывающие импортируют функции из
``app.message_reads.digest`` / ``app.message_reads.raw``, а не отсюда.
"""

from typing import Any, Dict, Optional

MOSCOW_TZ = "Europe/Moscow"

# Единственное место, где формулируется подзапрос исключения спамеров.
# Подставляется во все digest-запросы через f-string (это статическая
# Python-константа, не внешние данные — не SQL-инъекция).
SPAM_EXCLUSION_SQL = """AND NOT EXISTS (
                  SELECT 1 FROM spam_users su
                  WHERE su.chat_id = m.chat_id AND su.user_id = m.user_id
              )"""

# Единственное место, где формулируется каст временной метки к
# "московскому" календарному дню.
#
# ИЗВЕСТНЫЙ БАГ, унаследованный из app/models.py бит-в-бит (сохранён
# намеренно — FR-6 PRD-01 требует точного переноса поведения; фикс вне
# скоупа, см. https://github.com/gihar/clio/issues/9): двойной каст
# временной зоны на TIMESTAMPTZ-колонке ``sent_at`` исторически двигает
# границу дня на 03:00 UTC (фактически UTC-3), а не на 21:00 UTC
# предыдущего дня, как подразумевает "московский" (UTC+3) в названии.
MOSCOW_DAY_SQL = f"(m.sent_at AT TIME ZONE 'UTC' AT TIME ZONE '{MOSCOW_TZ}')::date"

# Единственное место, где перечислены колонки полной выборки сообщения
# (используется всеми raw-запросами).
FULL_MESSAGE_COLUMNS_SQL = """
            m.message_id,
            m.message_type,
            m.text,
            m.caption,
            m.sent_at,
            m.edited_at,
            m.reply_to_message_id,
            u.id as user_id,
            u.first_name,
            u.last_name,
            u.username"""


def row_to_full_message(row: Any) -> Dict[str, Optional[Any]]:
    """Проекция строки полной выборки (см. FULL_MESSAGE_COLUMNS_SQL) в dict.

    Единственное место, где строка результата превращается в dict с
    вложенным ``user{}`` (или ``None``, если у сообщения нет автора).
    """
    return {
        "message_id": row[0],
        "message_type": row[1],
        "text": row[2],
        "caption": row[3],
        "sent_at": row[4],
        "edited_at": row[5],
        "reply_to_message_id": row[6],
        "user": {
            "id": row[7],
            "first_name": row[8],
            "last_name": row[9],
            "username": row[10],
        } if row[7] else None,
    }
