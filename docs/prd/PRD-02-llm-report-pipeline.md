# PRD-02: Единый LLM-пайплайн отчётов с инъекцией `complete()`

- **Статус**: Draft
- **Приоритет**: P1 (Strong)
- **Зависимости**: желательно после PRD-01 (тогда фетчеры — уже чистые функции
  модуля чтения). Можно делать и до него — тогда фетчеры импортируются из `models`.
- **Источник**: Architecture review 2026-07-09, кандидат 2

## Контекст

Три сервиса — `summary.py` (110 строк), `strategy.py` (142), `analytics.py` (137) —
клоны одного конвейера: получить чат → guard «Чат не найден» → получить сообщения →
guard «пусто» → отформатировать строки → `.format()` шаблона промпта →
`generate_completion` → guard `None` → собрать dict `{success, error, ...}`.

При этом LLM-вызов не имеет seam: `generate_completion` импортируется по имени
(`summary.py:7`, `strategy.py:7`, `analytics.py:8`), сам достаёт конфиг из глобала
(`openrouter.py:32`) и схлопывает **все** виды отказа в `return None`
(`openrouter.py:36,70,73,76`): нет ключа, таймаут, HTTP-ошибка, битый JSON —
неразличимы. Каждый вызывающий заново придумывает сообщение об ошибке.

Итог: самая ценная бизнес-логика (сборка промптов, guard'ы, математика дат) —
**ноль тестов**; протестировать её можно только monkeypatch'ем внутренностей.

## Текущее состояние (доказательства)

- Клонированный конвейер: `app/services/summary.py:41-109`,
  `app/services/strategy.py:54-141`, `app/services/analytics.py:60-136`.
- Реконструкция ошибки у каждого вызывающего: `summary.py:94-101`,
  `strategy.py:123-131`, `analytics.py:135`.
- `rg -l "services|openrouter" tests/` — пусто: ни одного теста на сервисы и LLM-клиент.

Отличия сервисов (это параметры будущего пайплайна, а не причины для трёх копий):

| | summary | strategy | analytics |
|---|---|---|---|
| Фетчер | messages за 24ч | messages за 7/30 дней | счётчики по дням за 7 дней |
| Форматтер | `[HH:MM] @author: text` (обрез 500) | `[dd.mm HH:MM] @author: [type] text` (обрез 300, reverse) | строка `date: count` |
| Промпт | `SUMMARY_PROMPT_TEMPLATE` | `STRATEGY_PROMPT_TEMPLATE` | `ANALYTICS_PROMPT_TEMPLATE` |
| max_tokens / timeout | 500 / 30.0 | 800 / 45.0 | 150 / 30.0 |
| LLM обязателен | да | да | **нет** — при отказе LLM `success: True`, `ai_comment: None` |

## Цель

Один глубокий модуль-пайплайн: `run_report(spec, ...)` с маленьким интерфейсом,
за которым спрятан весь конвейер. LLM-вызов — за настоящим seam: инжектируемый
адаптер `complete()`, у которого два воплощения — OpenRouter HTTP в проде и фейк
в тестах. Отказы LLM — типизированы, маппинг «вид отказа → русское сообщение
пользователю» живёт в одном месте.

## Целевой интерфейс (предложение; детали — на усмотрение исполнителя)

```python
# app/services/completion.py — seam LLM-вызова
class CompletionError(Exception):
    kind: str  # 'not_configured' | 'timeout' | 'http_error' | 'bad_response'

# Протокол адаптера (прод-реализация — на базе текущего openrouter.py):
async def complete(prompt: str, *, system_prompt: str | None = None,
                   max_tokens: int = 1000, timeout: float = 30.0) -> str
# возвращает текст ИЛИ бросает CompletionError(kind=...) — никаких None.

# app/services/reports.py — пайплайн
@dataclass(frozen=True)
class ReportSpec:
    fetch: Callable[..., Awaitable[Any]]        # данные для отчёта
    format_data: Callable[[Any], str]           # данные -> текст для промпта
    system_prompt: str
    prompt_template: str                        # .format(...)
    build_result: Callable[..., dict]           # сборка итогового dict
    max_tokens: int
    timeout: float

async def run_report(spec: ReportSpec, chat_id: int, *,
                     complete: CompleteFn = openrouter_complete, **params) -> dict
```

Публичные функции `generate_chat_summary(chat_id)`,
`generate_content_strategy(chat_id, period)`, `generate_chat_analytics(chat_id)`
сохраняются (их использует `web/routes.py:28-30`) и становятся тонкими вызовами
пайплайна со своими spec'ами. Инъекция — параметром с прод-дефолтом.

## Функциональные требования

- **FR-1**: Появляется единственная реализация конвейера; `summary` и `strategy`
  ОБЯЗАНЫ идти через неё. `analytics` ОБЯЗАН использовать тот же `complete()`-seam
  и общий маппинг ошибок; проходить через общий пайплайн — если укладывается
  (у него LLM опционален и есть ветка `total == 0` без LLM-вызова).
- **FR-2**: `complete()` больше не возвращает `None`: отказы — типизированное
  исключение (или result-тип) с машиночитаемым `kind` из
  {`not_configured`, `timeout`, `http_error`, `bad_response`}.
  Текущее логирование ошибок сохраняется.
- **FR-3**: Маппинг `kind` → русское сообщение пользователю определён ровно один раз.
  Существующие тексты сообщений сохраняются: «Не удалось сгенерировать саммари.
  Попробуйте позже.», «Не удалось сгенерировать отчёт. Попробуйте позже.»,
  «Не удалось получить AI-комментарий», «Чат не найден», «Нет сообщений…».
- **FR-4**: Формы JSON-ответов сохраняются **по-ключево для каждой ветки**
  (их читает фронтенд админки):
  - summary: `{success, error, summary, messages_count, period}` во всех ветках;
  - strategy: успех/LLM-отказ — `{success, error, chat_type, period, date_range,
    messages_analyzed, report?}`; валидация периода / чат не найден / нет сообщений —
    `{success, error}` (как сейчас, `strategy.py:66-93`);
  - analytics: `{success, chat_type, period, daily_messages, total, average,
    ai_comment, error}`; ветка «чат не найден» — `{success, error}`.
- **FR-5**: Зависимости пайплайна (фетчер данных, lookup чата, `complete`)
  принимаются как параметры с прод-дефолтами — тесты подставляют фейки без
  monkeypatch'а модульных глобалов.
- **FR-6**: `openrouter.py` остаётся единственным местом знания про HTTP, заголовки,
  payload и `OPENROUTER_API_URL`. Допустимо читать конфиг внутри прод-адаптера
  (как сейчас), но проверка `has_openrouter` маппится в `kind='not_configured'`.

## Инварианты (нельзя сломать)

1. HTTP-статусы эндпоинтов не меняются: `routes.py` по-прежнему получает dict
   с `success` и отдаёт `200/400` (`routes.py:332,357,389`), guard 503 — как сейчас.
2. analytics при `total == 0` возвращает `success: True` без вызова LLM
   (`analytics.py:95-105`).
3. strategy принимает только `period ∈ {"week","month"}` (`strategy.py:65`).

## Требования к тестам

Все новые тесты — unit, без Postgres и без сети (фейковые фетчеры и фейковый
`complete`). Минимальный набор:

- **T-1**: happy path каждого из трёх отчётов: результат-dict поключево совпадает
  с текущей формой; в промпт попали отформатированные сообщения и заполнены
  переменные шаблона.
- **T-2**: ветки отказов: чат не найден; нет сообщений; каждый `kind` отказа
  `complete()` → корректное русское сообщение и `success: False`
  (для analytics — `success: True`, `ai_comment: None`).
- **T-3**: форматтеры: обрезка текста (500 для summary, 300 для strategy),
  хронологический порядок строк в промпте strategy (reverse от DESC-выборки).
- **T-4**: `_fill_missing_days` (`analytics.py:29`): пустой вход, дыры в середине.
- **T-5**: прод-адаптер `complete`: маппинг таймаута/HTTP-ошибки/битого JSON в
  правильный `kind` (httpx мокается, например через `httpx.MockTransport` —
  без новых зависимостей).

## Критерии приёмки

- [ ] `python -m pytest` — зелёный; новые unit-тесты не требуют Postgres/сети.
- [ ] `rg "return None" app/services/openrouter.py` (или модуля-наследника) — 0 вхождений.
- [ ] Конвейер «fetch → guard → format → prompt → complete → result» реализован
      один раз; `rg "Не удалось сгенерировать" app/` — не более 2 файлов
      (шаблоны сообщений + одно место маппинга).
- [ ] Сигнатуры `generate_chat_summary / generate_content_strategy /
      generate_chat_analytics` не изменились; `web/routes.py` не менялся
      (кроме, возможно, импортов).
- [ ] Суммарный объём `app/services/` не вырос относительно текущих ~470 строк
      (без учёта тестов): дублирование удалено, а не переупаковано.

## Вне объёма

- Изменение промптов, моделей, max_tokens/timeout.
- Ретраи, кэширование LLM-ответов, стриминг.
- Обёртка эндпоинтов в `routes.py` (PRD-05).
- Полная инъекция `Config` во всё приложение (глобал `get_config()` вне
  LLM-адаптера остаётся как есть).
