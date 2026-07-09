"""Единая точка чтения сообщений чата: инвариант digest-visible vs raw.

Инвариант: аналитические выборки (саммари, стратегия, аналитика) —
``app.message_reads.digest`` — ИСКЛЮЧАЮТ сообщения помеченных спамеров.
Сырая вьюха админки и экспорт — ``app.message_reads.raw`` — спамеров
НЕ фильтруют: это осознанный скоуп, зафиксированный
tests/test_spam_filtering.py.

Спам-пометка (таблица ``spam_users``) скоупится по чату: мут в одном чате
не влияет на видимость сообщений того же юзера в другом чате.

Московский календарный день (UTC+3) НАМЕРЕН начинаться в 21:00 UTC
предыдущего дня. ИЗВЕСТНОЕ РАСХОЖДЕНИЕ, унаследованное из app/models.py
бит-в-бит (см. MOSCOW_DAY_SQL и tests/test_message_reads.py): двойной
каст временной зоны, применённый к TIMESTAMPTZ-колонке ``sent_at``, на
деле двигает границу дня на 03:00 UTC (обратный знак смещения), а не
на 21:00 UTC. Это существующий баг продакшн-кода, предшествующий PRD-01;
семантика сохранена намеренно (FR-6 требует точного переноса поведения),
фикс — отдельный тикет вне скоупа этого модуля.

Этот модуль содержит общие строительные блоки для digest/raw-запросов:
SQL-фрагмент исключения спамеров (определён один раз), каст московского
дня (определён один раз) и проекцию строки полной выборки в dict с
вложенным ``user{}`` (определена один раз).
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
# московскому календарному дню.
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
