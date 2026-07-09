# PRD-03: Разделение `app/models.py` по концепциям

- **Статус**: Draft
- **Приоритет**: P2 (Worth exploring)
- **Зависимости**: выполнять ПОСЛЕ PRD-01 (он забирает из `models.py` чтение сообщений).
  Если PRD-01 ещё не сделан — read-функции сообщений переносить в `app/message_reads.py`
  чистой релокацией без дедупликации (дедупликация — предмет PRD-01).
  Конфликтует по файлам с PRD-04 — не выполнять параллельно.
- **Источник**: Architecture review 2026-07-09, кандидат 3

## Контекст

`app/models.py` — 983 строки, god-модуль и хаб всего приложения: его импортируют
handlers, все три сервиса, web/routes, main и все тесты. Внутри — минимум шесть
несвязанных ответственностей. Любое изменение любой из них трогает зависимость
каждого слоя. Это чисто механический рефакторинг ради locality: одна концепция —
один модуль.

## Текущее состояние (карта содержимого `app/models.py`)

| Строки | Ответственность | Содержимое |
|--------|-----------------|------------|
| 17–154 | DDL + миграции | `CREATE_TABLES_SQL`, `MIGRATION_SQL` |
| 157–180 | инициализация схемы | `create_tables`, `run_migrations`, `init_database` |
| 183–232 | разбор Telegram-объектов | `detect_message_type`, `get_forward_chat_id` |
| 235–327 | запись (Telegram → строки) | `save_user`, `save_chat`, `save_message` |
| 330–368 | spam-пометки | `flag_spam_user`, `unflag_spam_user` |
| 371–501 | join-заявки | `save_join_request_fields`, `get_pending_fresh_join_requests`, `mark_join_requests_status`, `get_join_requests` |
| 504–890 | админ-чтение | `ChatStats`, `Stats`, `DashboardChat`, `get_stats`, `get_chats_with_stats`, `get_chat_by_id`, `get_users`, `get_dashboard_data` |
| 893–983 | digest-чтение сообщений | `get_messages_for_summary`, `get_daily_message_counts`, `get_messages_for_period` (уходит в PRD-01) |

Плюс мёртвый импорт: `from .database import get_cursor, get_connection`
(`models.py:11`) — `get_connection` в модуле не используется.

## Цель

Вместо одного хаба — набор модулей по одной концепции в каждом, с маленькими
интерфейсами. Каждый слой импортирует только то, что ему нужно.

## Целевая структура

```
app/
  schema.py         # CREATE_TABLES_SQL, MIGRATION_SQL, create_tables,
                    # run_migrations, init_database
  ingest.py         # detect_message_type, get_forward_chat_id,
                    # save_user, save_chat, save_message
  spam_flags.py     # flag_spam_user, unflag_spam_user
  join_requests.py  # save_join_request_fields, get_pending_fresh_join_requests,
                    # mark_join_requests_status, get_join_requests
  admin_reads.py    # ChatStats, Stats, DashboardChat, get_stats,
                    # get_chats_with_stats, get_chat_by_id, get_users,
                    # get_dashboard_data
  message_reads.py  # уже существует после PRD-01
```

Имена файлов — предложение; исполнитель может уточнить, сохранив принцип
«одна концепция — один модуль». `app/models.py` в конце **удаляется**.

## Функциональные требования

- **FR-1**: Чистая релокация: тела функций, SQL и докстринги не меняются
  (исключение — FR-4). Никаких изменений логики «заодно».
- **FR-2**: Все импортёры обновляются: `app/bot/handlers.py:13-20`,
  `app/web/routes.py:17-27`, `app/services/*.py`, `main.py`
  (`init_database`), `tests/conftest.py:13`, все `tests/test_*.py`.
- **FR-3**: `app/models.py` удалён; re-export-шима не остаётся.
- **FR-4**: Мёртвый импорт `get_connection` не переезжает. `get_connection`
  остаётся в `app/database.py` (его использует `get_cursor`), но из
  новых модулей не импортируется.
- **FR-5**: Внутренние зависимости направлены правильно: `ingest` ←
  `spam_flags` и `join_requests` (обе вызывают `save_user`/`save_chat` для FK);
  циклических импортов нет.

## Инварианты (нельзя сломать)

1. Поведение БД идентично: те же таблицы, миграции, UPSERT'ы, каскады.
2. `main.py` продолжает инициализировать схему до старта бота и веб-сервера.
3. Порядок инициализации в `init_database` (таблицы → миграции → индекс
   `message_type`) сохраняется (`models.py:171-180`).

## Требования к тестам

- **T-1**: Все существующие тесты проходят; в тестах меняются только import-пути.
- **T-2**: Новых тестов не требуется (механический перенос), но smoke-запуск
  приложения обязателен: `python -c "import main"` без ошибок импорта.

## Критерии приёмки

- [ ] `python -m pytest` — зелёный.
- [ ] Файл `app/models.py` отсутствует; `rg "from .models|from app.models|app\.models" --type py` — 0 вхождений.
- [ ] Каждый новый модуль < 400 строк.
- [ ] `rg "get_connection" app/ --type py` — вхождения только в `app/database.py`.
- [ ] `python -c "import main"` — успешно.
- [ ] Диффы функций — только перенос (проверяемо ревью: `git diff --color-moved`).

## Вне объёма

- Дедупликация SQL внутри перенесённых функций (PRD-01 уже сделал это для чтения
  сообщений; админ-чтение не дедуплицируем здесь).
- Интерфейс `record_message` (PRD-04).
- Переезд на ORM, изменение схемы, новые индексы.
