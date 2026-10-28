# Бэкенд мониторинга эпизоотической ситуации

Серверная часть сервиса «Эпизоомонитор». Загружает оперативные PDF-сводки Россельхознадзора, распознаёт события и карантины, рассчитывает уровень значимости по регионам и отдаёт данные через REST API: карта и карточка региона, справочники, лента событий, саммари, анонимные профили хозяйств с дайджестом, проверка перед перевозкой животных и предложения продуктов банка фермеру. Оповещения подписчикам рассылает Telegram-бот.

Стек: Python 3.12, FastAPI, SQLAlchemy (async), Alembic, PostgreSQL 16, PyMuPDF, APScheduler, aiogram.

## Запуск

### Docker

```bash
cp .env.example .env
# Укажите собственные POSTGRES_PASSWORD и API_KEY в .env.
docker compose up --build -d
```

Сервис `init` применяет миграции и загружает справочники, после него стартуют `api` и `worker`. API: <http://localhost:8000/docs>, проверка БД: <http://localhost:8000/health>.

Первичная загрузка истории за последние 365 дней:

```bash
docker compose exec api python -m etl.cli backfill
```

Telegram-бот запускается отдельным профилем (нужны `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `FRONTEND_URL` в `.env`):

```bash
docker compose --profile telegram up --build -d
```

### Локально

Нужны Python 3.12+, `uv` и PostgreSQL 16:

```bash
uv sync --frozen
cp .env.example .env
uv run python -m app.db.init
uv run uvicorn app.main:app --reload
```

Планировщик и бот — в отдельных терминалах: `uv run python -m worker.scheduler`, `uv run python -m bot.main`.

## Архитектура

```
app/
  api/v1/        HTTP-роуты (префикс /api/v1)
  services/      бизнес-логика: скоринг, карантины, саммари, дайджест,
                 проверка маршрута, предложения банка, уведомления
  repositories/  запросы к БД
  models/        модели SQLAlchemy
  schemas/       Pydantic-схемы запросов и ответов
  core/          конфигурация, ошибки, логирование, безопасность
  db/            подключение, инициализация и справочники
etl/             загрузка PDF, парсинг daily/weekly сводок, нормализация,
                 загрузка в БД, RSS-новости, сверка (CLI: python -m etl.cli)
worker/          планировщик: ETL 09:00/15:00 МСК, по понедельникам —
                 оповещения и дайджест
bot/             Telegram-бот: привязка хозяйства, статус, настройки, дайджест
```

Поток данных: `etl` скачивает и кэширует PDF → парсит события и карантины → сохраняет в PostgreSQL → `services` считают уровни регионов → `api` отдаёт их фронтенду, а `worker` и `bot` рассылают оповещения подписчикам. API, worker и бот используют одну БД и общий слой сервисов.

Дополнительно: источники данных — `docs/data-sources.md`, настройка провайдеров саммари — `docs/summary-providers.md`, схема API — `docs/openapi.json`.
