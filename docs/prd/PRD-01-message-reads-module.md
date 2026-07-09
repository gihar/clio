# PRD-01: Модуль чтения сообщений — инвариант «digest-visible» в одном месте

- **Статус**: Draft
- **Приоритет**: P1 (Strong)
- **Зависимости**: нет. Конфликтует по файлам с PRD-03 и PRD-04 — не выполнять параллельно.
- **Источник**: Architecture review 2026-07-09, кандидат 1

## Контекст

Ключевой продуктовый инвариант: **аналитические выборки (саммари, стратегия, аналитика)
исключают сообщения помеченных спамеров, а сырая вьюха админки — нет**. Сегодня этот
инвариант — эмерджентное свойство того, в каких из ~7 read-запросов случайно есть
подзапрос `NOT EXISTS (SELECT 1 FROM spam_users ...)`. Владеющего модуля нет:
новый запрос для дайджеста может молча забыть фильтр, и единственное, что фиксирует
асимметрию — тест `tests/test_spam_filtering.py`.

## Текущее состояние (доказательства)

Дублированный спам-фильтр (три копии одного подзапроса):

- `app/models.py:906-909` — `get_messages_for_summary` (24ч, только text, ASC, limit)
- `app/models.py:931-934` — `get_daily_message_counts` (счётчики по московским дням)
- `app/models.py:965-968` — `get_messages_for_period` (N дней, text ИЛИ caption, DESC, limit)

Сырые (нефильтрующие — намеренно) запросы:

- `app/models.py:601` — `get_chat_messages` (пагинация, фильтр по типу, DESC)
- `app/models.py:680` — `get_chat_messages_by_date` (московский день, ASC)
- `app/models.py:728` — `get_chat_messages_by_date_range` (диапазон московских дней, ASC)

Сопутствующее дублирование в тех же запросах:

- Каст московского дня `(m.sent_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Moscow')::date`
  — 4 копии: `app/models.py:703,751,752,926`.
- Проекция строки в dict с вложенным `user{}` — 3 идентичные копии:
  `app/models.py:638-655, 708-725, 757-774`.
- **f-string-интерполяция в SQL**: `INTERVAL '{days} days'` в `models.py:924` и `:953`.
  Сейчас не инъекция (days — внутренний int), но это запрещённый паттерн.

Вызывающие стороны:

- `app/services/summary.py:6` → `get_messages_for_summary`
- `app/services/strategy.py:6` → `get_messages_for_period`
- `app/services/analytics.py:7` → `get_daily_message_counts`
- `app/web/routes.py:17-27` → `get_chat_messages`, `get_chat_messages_by_date`,
  `get_chat_messages_by_date_range`

## Цель

Один глубокий модуль чтения сообщений, чей интерфейс **именует** различие
digest-visible vs raw, а реализация прячет: спам-исключение (×1), каст московского
дня (×1), оконную фильтрацию (×1), маппер строки в dict (×1).

## Целевой интерфейс (предложение; детали — на усмотрение исполнителя)

Новый модуль `app/message_reads.py`:

```python
# Digest-visible: исключают помеченных спамеров. Для саммари/стратегии/аналитики.
async def digest_messages_last_hours(chat_id: int, *, hours: int = 24, limit: int = 500) -> list[dict]
async def digest_messages_last_days(chat_id: int, *, days: int, limit: int = 500) -> list[dict]
async def digest_daily_counts(chat_id: int, *, days: int = 7) -> list[dict]

# Raw: НЕ фильтруют спамеров. Для сырой вьюхи админки и экспорта.
async def raw_messages(chat_id: int, *, limit: int = 100, offset: int = 0,
                       message_type: str | None = None) -> list[dict]
async def raw_messages_for_day(chat_id: int, date_str: str) -> list[dict]
async def raw_messages_for_range(chat_id: int, date_from: str, date_to: str) -> list[dict]
```

Имена можно менять, но публичные имена ОБЯЗАНЫ делать различие digest/raw явным
(префиксы, либо два подмодуля). Докстринг модуля обязан формулировать инвариант словами.

## Функциональные требования

- **FR-1**: Все шесть перечисленных read-функций переезжают в один новый модуль
  (`app/message_reads.py` или эквивалент). `app/models.py` их больше не содержит.
- **FR-2**: SQL-фрагмент спам-исключения определён в модуле ровно один раз
  (константа или функция-билдер) и подставляется во все digest-запросы.
- **FR-3**: Каст московского дня определён ровно один раз и переиспользуется.
- **FR-4**: Проекция «строка → dict с вложенным user{}» определена ровно один раз.
- **FR-5**: f-string-интерполяция интервалов заменена на параметризованный SQL,
  например `m.sent_at >= NOW() - make_interval(days => %s)`.
- **FR-6**: Семантика каждого вызова сохранена ТОЧНО. Внимание к тонкостям:
  - `get_messages_for_summary`: окно 24ч, `text IS NOT NULL`, сортировка **ASC**,
    `LIMIT` берёт **старейшие** N окна; проекция `{text, author, sent_at}`;
    `author = COALESCE(username, first_name, 'Unknown')`.
  - `get_messages_for_period`: окно N дней, `text OR caption IS NOT NULL`,
    сортировка **DESC**, `LIMIT` берёт **новейшие** N; проекция
    `{text: text|caption, author, sent_at, type}`.
  - `get_daily_message_counts`: группировка по московскому дню, результат
    `{date: iso-строка, count}` по возрастанию дня.
  - Raw-функции: полная проекция c `user{}`, порядок и пагинация как сейчас.
- **FR-7**: Вызывающие стороны (`services/*`, `web/routes.py`) обновляют импорты.
  В `app/models.py` временных re-export'ов не оставлять.
- **FR-8** (примечание, не блокер): строка `"timezone": "UTC+3"` в
  `routes.py:213,276` описывает тот же инвариант, что и каст московского дня.
  Если модуль вводит константу таймзоны — экспортировать её и использовать в routes;
  иначе оставить как есть и не трогать.

## Инварианты (нельзя сломать)

1. Digest-выборки исключают спамеров; спам-пометка скоупится по чату
   (`tests/test_spam_filtering.py:90` — flag в чате A не влияет на чат B).
2. Сырая вьюха админки показывает сообщения спамеров.
3. Границы дня сохраняются **бит-в-бит с текущим продом**. ⚠️ Известный баг
   (найден при реализации, подтверждён эмпирически): двойной
   `AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Moscow'` на TIMESTAMPTZ-колонке
   даёт **обратный знак** — день фактически переключается в 03:00 UTC (UTC-3),
   а не в 21:00 UTC (UTC+3), и результат вдобавок зависит от session TimeZone.
   В рамках PRD-01 поведение НЕ исправлять (фикс ретроактивно перегруппирует
   старые дни в экспортах/аналитике — продуктовое решение); заведён отдельный
   bug-issue с меткой `ready-for-human`.

## Требования к тестам

- **T-1**: Все существующие тесты проходят; в них можно менять только import-пути.
- **T-2**: Новые integration-тесты нового модуля через его публичный интерфейс —
  минимум: границы окна (сообщение старше 24ч не попадает в
  `digest_messages_last_hours`), пагинация/фильтр по типу в `raw_messages`,
  граница дня в `raw_messages_for_day` — под **фактическое** поведение
  (см. инвариант 3): сообщение в 02:59 UTC относится к предыдущему дню,
  в 03:00 UTC — к текущему; тест назван честно (legacy UTC-3) и ссылается
  на bug-issue.

## Критерии приёмки

- [ ] `python -m pytest` — зелёный.
- [ ] `rg -c "NOT EXISTS" app/` — ровно 1 вхождение (в новом модуле).
- [ ] `rg -c "Europe/Moscow" app/` — ровно 1 вхождение.
- [ ] `rg "INTERVAL '\{" app/` — 0 вхождений (нет f-string SQL).
- [ ] `rg "get_messages_for_summary|get_messages_for_period|get_daily_message_counts|get_chat_messages" app/models.py` — 0 вхождений.
- [ ] Публичные имена модуля различают digest/raw; докстринг модуля формулирует инвариант.
- [ ] Новый модуль < 400 строк.

## Вне объёма

- Запросы дашборда/статистики (`get_stats`, `get_dashboard_data`, `get_users`,
  `get_chats_with_stats`) — остаются в `models.py`, ими займётся PRD-03.
  Открытый продуктовый вопрос (НЕ решать здесь): `get_dashboard_data` показывает
  топ-пользователей недели **без** спам-фильтра — намеренно ли, решает владелец продукта.
- Изменение форм JSON-ответов API.
- Кэширование, оптимизация запросов.
