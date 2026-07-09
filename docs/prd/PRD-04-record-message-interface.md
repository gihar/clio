# PRD-04: Тестопригодный интерфейс записи сообщений `record_message`

- **Статус**: Draft
- **Приоритет**: P2 (Worth exploring)
- **Зависимости**: конфликтует по файлам с PRD-01 и PRD-03 — не выполнять
  параллельно с ними. Если PRD-03 уже сделан, работа идёт в `app/ingest.py`;
  иначе — в `app/models.py`.
- **Источник**: Architecture review 2026-07-09, кандидат 4

## Контекст

Единственный публичный способ создать строку в `messages` — 
`save_message(msg: telegram.Message, is_edit: bool)` (`app/models.py:277`), который
требует полностью собранный объект `telegram.Message`. Собирать его в тестах
непрактично, поэтому три места в тестах **обходят интерфейс** сырым SQL,
завязанным на порядок колонок:

- `tests/test_spam_filtering.py:23-32` — хелпер `_insert_message` с
  `INSERT INTO messages (...)`;
- `tests/test_spam_filtering.py:96-102` — ещё один инлайновый `INSERT` на две строки;
- `tests/test_spam_unmute.py` — свой дубль вставки.

Интерфейс перестал быть тестовой поверхностью: тесты и продакшен пересекают
seam персистентности в разных местах. Дублированный сырой SQL в тестах — это
знание о схеме, размазанное по файлам.

## Цель

Запись сообщения получает интерфейс с плоскими параметрами — `record_message` —
через который проходят **и** продакшен (через Telegram-адаптер `save_message`),
**и** тесты. Знание о том, как объект `telegram.Message` раскладывается в колонки
(тип сообщения, forward_origin, edit_date), концентрируется в адаптере.

## Целевой интерфейс (предложение; детали — на усмотрение исполнителя)

```python
async def record_message(
    *,
    chat_id: int,
    message_id: int,
    user_id: int | None,
    sent_at: datetime,
    message_type: str = "text",
    text: str | None = None,
    caption: str | None = None,
    reply_to_message_id: int | None = None,
    forward_from_chat_id: int | None = None,
    raw_message: dict | None = None,
) -> None
    # INSERT ... ON CONFLICT (chat_id, message_id) DO NOTHING — как сейчас.

async def record_message_edit(
    *, chat_id: int, message_id: int, edited_at: datetime,
    text: str | None = None, caption: str | None = None,
    raw_message: dict | None = None,
) -> None
    # UPDATE ... WHERE chat_id AND message_id — как сейчас.
```

`save_message(msg, is_edit)` сохраняет сигнатуру и текущее поведение и становится
Telegram-адаптером: guard `from_user`, `save_user` + `save_chat`,
`detect_message_type`, `get_forward_chat_id`, `json.dumps(msg.to_dict())` —
и вызов `record_message` / `record_message_edit`.

## Функциональные требования

- **FR-1**: Появляются `record_message` и `record_message_edit` с плоскими
  параметрами (keyword-only). Единственные места в приложении, где есть
  `INSERT INTO messages` / `UPDATE messages`.
- **FR-2**: `save_message` рефакторится в адаптер поверх них; его сигнатура и
  наблюдаемое поведение не меняются (включая guard «нет from_user → return»,
  `models.py:279-280`).
- **FR-3**: `record_message` НЕ апсертит users/chats — выполнение FK-констрейнтов
  остаётся ответственностью вызывающего (адаптер это уже делает; тесты делают
  явно через `save_user`/`save_chat`, как сейчас).
- **FR-4**: Тестовые хелперы с сырым SQL (`_insert_message` и инлайновые INSERT'ы)
  заменяются вызовами `record_message`. Assert'ы тестов не меняются.
- **FR-5**: Лёгкая валидация на границе: `sent_at` обязателен;
  `message_type` — непустая строка. При нарушении — `ValueError` с понятным
  сообщением (тише падать нельзя — это программная ошибка вызывающего).

## Инварианты (нельзя сломать)

1. Дедупликация по составному ключу: повторный `record_message` с тем же
   `(chat_id, message_id)` — no-op (ON CONFLICT DO NOTHING).
2. Редактирование не создаёт строку, если сообщения нет (UPDATE ничего не находит —
   тихо, как сейчас).
3. `save_message` по-прежнему апсертит юзера и чат до вставки сообщения.

## Требования к тестам

- **T-1**: Все существующие тесты проходят; в них сырые INSERT'ы заменены на
  `record_message`, assert'ы нетронуты.
- **T-2**: Новые integration-тесты интерфейса: дедупликация по
  `(chat_id, message_id)`; `record_message_edit` обновляет text/edited_at
  существующей строки и не создаёт новой; `ValueError` на невалидный вход.
- **T-3**: Существующий glue-тест `tests/test_spam_handler.py` (реальные
  Telegram-объекты через `chat_member_handler`) остаётся нетронутым — он
  покрывает адаптерную сторону seam'а.

## Критерии приёмки

- [ ] `python -m pytest` — зелёный.
- [ ] `rg "INSERT INTO messages" tests/` — 0 вхождений.
- [ ] `rg -c "INSERT INTO messages" app/` — ровно 1 вхождение;
      `rg -c "UPDATE messages" app/` — ровно 1 вхождение.
- [ ] Сигнатура `save_message(msg, is_edit=False)` не изменилась; вызывающие
      (`app/bot/handlers.py:100,124`) не менялись.

## Вне объёма

- Изменение схемы `messages`, добавление колонок.
- Batch-вставка, очереди — из «Future Enhancements» проекта.
- Перенос модулей (PRD-03); фейковый in-memory адаптер персистентности
  (один адаптер = гипотетический seam; вводить фейк будем, когда появится
  второй потребитель).
