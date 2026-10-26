# Бэкенд мониторинга эпизоотической ситуации

FastAPI, PostgreSQL 16, ETL оперативных PDF Россельхознадзора, Telegram-бот и планировщик. Реализованы карта и карточка региона, справочники, события, карантины, саммари, анонимные хозяйства, дайджест, проверка перед перевозкой и предложения продуктов банка фермеру. Фронтенд находится вне этой части проекта.

## Запуск в Docker

В каталоге `backend`:

```bash
cp .env.example .env
# Укажите собственные POSTGRES_PASSWORD и API_KEY в .env.
docker compose up --build -d
```

Сервис `init` применяет Alembic и загружает справочники. `api` и `worker` запускаются после него. API: <http://localhost:8000/docs>; OpenAPI: <http://localhost:8000/openapi.json>; проверка подключения к БД: <http://localhost:8000/health>. PostgreSQL наружу не публикуется, API доступен на localhost. Для доступа с другого компьютера настройте опубликованный адрес самостоятельно.

Первичная загрузка доступной истории за последние 365 дней:

```bash
docker compose exec api python -m etl.cli backfill
```

По умолчанию работает шаблонный провайдер саммари. Для Yandex AI Studio задайте `SUMMARY_PROVIDER=yandex`, `YANDEX_API_KEY`, `YANDEX_FOLDER_ID` и `YANDEX_MODEL=yandexgpt-5-lite` в `.env`, затем пересоберите API. Пошаговая настройка — в `docs/summary-providers.md`. Для Telegram заполните `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` и `FRONTEND_URL`, затем:

```bash
docker compose --profile telegram up --build -d
```

Без токена worker выполняет ETL. При наличии токена отправляет уведомления подписчикам после загрузки. `/start <UUID>` привязывает хозяйство только в личном чате; `/status`, `/settings`, `/digest`, `/stop` используют тот же профиль и сервисы, что API. Ссылка `t.me/...` содержит токен хозяйства — это секрет доступа к анонимному профилю, его нельзя публиковать. Веб-API не принимает произвольный `chat_id`: связь создаёт бот. Повторная привязка к другому чату запрещена до удаления подписки.

## Деплой

Схема как в jobadapt: GitHub Actions → registry → SSH → Docker Compose v2. Стенд один — prod на `epizoo-demo-stand-2026.ru`: клиент (репозиторий epizoo-client) и API по `/api/` за nginx хоста.

- `.github/workflows/checks.yml` — pull request и push в `main`/`dev`: ruff (lint и format), `alembic check`, `pytest` против PostgreSQL 16 (включая конкурентный тест) и проверка `compose.prod.yaml`.
- `.github/workflows/release-deploy.yml` — опубликованный GitHub Release или ручной запуск с тега (Use workflow from → Tags): проверки, сборка образа `<версия>` и `latest` (версия — тег без префикса `v`) и деплой. Ручной запуск с ветки ничего не собирает.

Деплой по SSH: в `DEPLOY_DIR` копируется `compose.prod.yaml`, из secrets собирается `.deploy.env` (права 600), затем `docker compose pull` → запуск базы → миграции и справочники (`run --rm migrator`, то есть `python -m app.db.init`) → `up -d --wait` (ждёт healthcheck API) → `docker image prune -af`. Тома с данными остаются. Бот запускается, только если задан `TELEGRAM_BOT_TOKEN`.

GitHub environment `release`:

| Secret | Значение |
|---|---|
| `REGISTRY_URL` | registry host[:port], без https:// |
| `REGISTRY_REPO` | путь Docker-репозитория сервера |
| `REGISTRY_USER`, `REGISTRY_TOKEN` | доступ к registry |
| `SSH_HOST`, `SSH_USER`, `SSH_KEY` | сервер деплоя |
| `DEPLOY_DIR` | абсолютный путь каталога на сервере (не тот же, что у клиента) |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | база в Compose |
| `DATABASE_URL` | `postgresql+asyncpg://USER:PASSWORD@db:5432/DB`, пароль percent-encode |
| `API_KEY` | ключ закрытых API; без него `POST /internal/etl/run` недоступен |
| `FRONTEND_URL` | `https://epizoo-demo-stand-2026.ru` — для ссылок из бота |
| `CORS_ORIGINS` | необязательный: клиент и API на одном домене, CORS не нужен |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` | необязательные: бот и оповещения |
| `SUMMARY_PROVIDER`, `YANDEX_API_KEY`, `YANDEX_FOLDER_ID` | необязательные: `yandex` для саммари через YandexGPT |

Пустые необязательные secrets в `.deploy.env` не попадают — действуют значения по умолчанию. Значения — без переводов строк; кавычки и `$` экранируются при записи.

Сервер: bash, Docker с плагином Compose v2 и доступ к registry. API слушает `127.0.0.1:3021`, наружу его отдаёт nginx хоста по `/api/` (`nginx.host.conf` в epizoo-client). Postgres не публикуется. Compose-проект — `epizoo-server`.

После первого деплоя загрузите корпус публикаций (в `DEPLOY_DIR`):

```bash
docker compose --env-file .deploy.env -f compose.prod.yaml exec api python -m etl.cli backfill
```

Откат: поменяйте `VERSION` в `.deploy.env` на прошлую версию и выполните в `DEPLOY_DIR` `docker compose --env-file .deploy.env -f compose.prod.yaml up -d --wait`. Миграции автоматически не откатываются: проверьте совместимость версии со схемой БД.

## Локальный запуск

Python 3.12+, `uv` и PostgreSQL 16:

```bash
uv sync --frozen
cp .env.example .env
python -m app.db.init
uvicorn app.main:app --reload
```

Команды Python выполняйте через активированную `.venv` либо `uv run`. Для автономного просмотра и тестов можно явно задать `DATABASE_URL=sqlite+aiosqlite:///./local.sqlite3` перед `python -m app.db.init`. SQLite не предназначен для нескольких процессов API/worker/bot; рабочая БД — PostgreSQL.

В отдельных терминалах:

```bash
python -m worker.scheduler
python -m bot.main
```

## Данные и ETL

```bash
python -m etl.cli fetch --since 2025-10-14
python -m etl.cli load-cache
python -m etl.cli update
python -m etl.cli reconcile
```

`fetch` только заполняет кэш; `backfill` и `update` также загружают БД, пересчитывают карантины и читают RSS. `load-cache` получает индекс источника; для автономного запуска:

```bash
python -m etl.cli load-cache --manifest data/report-index.json
```

Индекс сохранён с публичного сайта 14.10.2026. Доступный корпус начинается 22.12.2025; отсутствие более ранних публикаций не означает отсутствия заболеваний. `data/cache` не входит в Git/образ, Docker использует отдельный volume. Для автономной загрузки внутри Docker скопируйте в контейнер индекс и PDF, либо выполните `backfill` с доступом к сети.

Скачивание ограничено одним стартом запроса в секунду, максимум три файла одновременно. Кэш хранит происхождение, ETag/Last-Modified и SHA256; обновление перепроверяет публикации, неизменные файлы не загружаются повторно при поддержке HTTP 304. Старый кэш без метаданных сохраняется при `fetch`; первый `update` проверит его по сети. Копии полученных версий сохраняются по хэшу в `data/cache/blobs`. Ошибка отдельного PDF возвращается в `issues`, остальные продолжают обрабатываться.

Одна ежедневная сводка на дату и одна еженедельная на период считаются логической публикацией. Новая версия заменяет текущие производные факты; исходные отчёты и журнал уведомлений остаются в БД. Weekly-счётчики исчезнувших регионов удаляются при замене версии. Повторная загрузка одинакового SHA256 не создаёт событий; возврат источника к ранее опубликованным байтам активирует эту версию.

Парсер сохраняет неоднозначные адреса и сноски в `reports.issues`, статус — `partial`. Полный текст и первоисточники остаются у события. Сверка сопоставляет ежедневные публикации с периодом еженедельной сводки, а не с датой акта: эти даты могут различаться. Расхождения возвращаются отчётом; они не исправляются придуманными событиями. При изменении самого алгоритма парсера для полного пересчёта старого корпуса используйте свежую БД; автоматическая миграция ранее распознанных событий при смене кода пока не реализована.

## Контракт API

Префикс `/api/v1`; ошибки — `{code, message}`. Неизвестный регион, вид или болезнь — 404; некорректные параметры — 422. При пустых данных ответ 200, уровень 0 и пустые коллекции. UUID хозяйства — единственный токен доступа в MVP.

- `GET /meta`, `/refs/regions`, `/refs/diseases`, `/refs/species`.
- `GET /map?species=cattle&disease=rabies&period=30` — 89 регионов с уровнями и счётчиками.
- `GET /regions/{code}`, `/regions/{code}/summary`, `/regions/{code}/history`.
- `GET /events?region=50&species=cattle&kind=quarantine_set&from=2026-09-01&to=2026-10-14&page=1&page_size=20`.
- `GET /diseases`, `/diseases/{slug}`.
- `POST /farms`, `GET/PUT /farms/{token}`, `GET /farms/{token}/dashboard`, `GET /farms/{token}/digest`.
- `POST /farms/{token}/telegram-link`, `PUT/DELETE /farms/{token}/subscription`.
- `GET /route-check?from=50&to=71&species=cattle`, `GET /offers?region=50&species=cattle`.
- `POST /internal/etl/run` — требует `X-API-Key`. При пустом серверном ключе доступ закрыт.

`period` — целое число дней 1–365, по умолчанию 30. `disease` — slug, `region` — двухзначный код ФНС, даты — ISO 8601; `page_size` 1–100. Виды: `cattle`, `small_ruminants`, `pigs`, `poultry`, `horses`, `bees`, `rabbits`, `carnivores`, `wildlife`. Пример тела хозяйства:

```json
{"region_code":"50","district":null,"species":["cattle"]}
```

Подписка: `min_level` 1–5, `include_neighbors`, `digest_enabled`; до Telegram-привязки `chat_id=null`. CSV выдаётся в UTF-8 с BOM. OpenAPI для фронтенда сохранён в `docs/openapi.json`; рабочая схема всегда доступна у API.

## Расчёты и расписание

Уровень события — `ceil(total)` с ограничением 1–5; без итогового балла используется эвристический `base_level`. Уровень региона учитывает события периода и все неснятые карантины независимо от возраста события. Сообщение о снятии не повышает уровень. Спустя 90 дней подтверждение карантина считается устаревшим (`unconfirmed`), но его уровень сохраняется консервативно. Неоднозначное снятие не закрывает несколько очагов; при совпадении названий учитываются районы и числовые части адреса.

Все задания используют `Europe/Moscow`: ETL ежедневно 09:00/15:00; в понедельник 09:00 ETL → оповещения → дайджест. Дайджест веба и бота охватывает предыдущую завершённую неделю понедельник–воскресенье. Старая публикация, загруженная после оформления подписки, не вызывает оповещение. Журнал и PostgreSQL-блокировки исключают обычные повторные и параллельные отправки. Если Telegram принял сообщение, а процесс упал до commit, повтор возможен: Telegram не предоставляет ключ идемпотентности для `sendMessage`.

## Проверки

```bash
pytest
ruff check app etl bot worker tests
ruff format --check app etl bot worker tests
alembic check
docker compose config --quiet
```

Конкурентное чтение и те же API-сценарии проверяются в отдельной PostgreSQL, создавая и удаляя только случайные тестовые схемы:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/test_db pytest tests/test_api.py
```

Нужны права на создание схем в этой тестовой БД. Обычный `pytest` использует SQLite; один конкурентный тест пропускается без `TEST_DATABASE_URL`. Предупреждения SWIG происходят из PyMuPDF. В `tests/fixtures` — 16 реальных PDF и независимые эталоны; 20 событий визуально сверены. Итоговая проверка корпуса и сверка — `docs/etl-validation.json`, `docs/reconciliation.json`, `docs/verification.md`.

## Ограничения перед публичным запуском

Неоднозначные записи требуют проверки по исходному PDF и актуальным актам. Сервис и проверка перевозки справочные; уровень 0 не удостоверяет благополучие региона. Геометрия и граф соседей основаны на контуре 2017 года с лицензией ODbL, подробности в `docs/data-sources.md`.

Каталог содержит 31 болезнь, проверенные по первичным ветправилам признаки и действия заполнены для восьми. У остальных 23 карточек они пустые; модель их не генерирует. Две банковские ссылки подтверждены официальным поисковым индексом, прямой HTTPS из текущей среды не подтверждён — повторная проверка нужна перед демонстрацией. Реальные запросы LLM и сообщения Telegram не проверялись: необходимы ваши ключи и тестовый чат. Параметры провайдеров описаны в `docs/summary-providers.md`.
