# BookingLab

Учебное приложение для бронирования переговорных комнат и практики API, UI, БД и Kafka тестирования. Оплата симулируется; реальные деньги не используются.

## Запуск

Установите и запустите Docker Desktop с поддержкой Docker Compose. Команды ниже выполняются из корня проекта. Порты 5173 и 8000 должны быть свободны. Python, Node.js и PostgreSQL на компьютере для запуска приложения не нужны.

1. Склонируйте репозиторий и перейдите в каталог:

```bash
git clone https://github.com/Anychos/automation-testing-project-base-app.git
cd automation-testing-project-base-app
```

2. Создайте локальный файл настроек `.env` из примера. Он обязателен и не отправляется в Git:

```powershell
Copy-Item .env.example .env
```

В Linux/macOS используйте `cp .env.example .env`. При необходимости измените настройки в `.env`: если меняете пароль PostgreSQL, обновите его также в `DATABASE_URL`. Перед публикацией приложения в сети замените `JWT_SECRET` и пароли.

3. Соберите и запустите сервисы, затем создайте начальные данные:

```bash
docker compose up -d --build
docker compose exec -e CONFIRM_TEST_DATA_OPERATION=yes backend python -m app.seed seed
```

Первый запуск может занять несколько минут: Docker скачивает образы и собирает приложение. Команда `seed` создаёт комнаты и учётные записи; для входа используйте значения `SEED_USER_EMAIL` / `SEED_USER_PASSWORD` или `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` из `.env`.

- UI: http://localhost:5173
- OpenAPI: http://localhost:8000/docs
- Проверки: `GET http://localhost:8000/api/health/live`, `GET http://localhost:8000/api/health/ready`

Проверить состояние сервисов можно командой `docker compose ps`, посмотреть сообщения — `docker compose logs -f`. Для остановки выполните `docker compose down`: данные PostgreSQL сохранятся в Docker volume. При ошибке запуска проверьте, что Docker запущен, `.env` создан и порты свободны.

Seed создаёт активные комнаты Small (2 места, 300 ₽/30 мин), Medium (4 места, 500 ₽/30 мин), Large (8 мест, 800 ₽/30 мин), пользователя и администратора с email/паролями из `.env`. Seed повторяемый. Броней изначально нет. Значения в `.env.example` пригодны только для локальной разработки.

## Режимы оплаты

`PAYMENT_MODE=stub` установлен по умолчанию. Фоновый обработчик проводит оплату без Kafka. При `TEST_MODE=true` API `POST /api/bookings/{id}/pay` принимает `{"test_scenario":"failure"}` или `{"test_scenario":"no_response"}`; без поля результат успешен. Ответ `/pay` — `202 PAYMENT_PENDING`; финальный статус можно получить через `GET /api/bookings/{id}`. Срок оплаты — 15 минут от создания брони.

```bash
# PowerShell:
$env:PAYMENT_MODE='kafka'; docker compose --profile payments up -d --build
docker compose stop payment-service

# bash:
PAYMENT_MODE=kafka docker compose --profile payments up -d --build
docker compose stop payment-service
```

Основной backend не зависит от готовности брокера и микросервиса. При их остановке запрос остаётся в outbox, бронь в `PAYMENT_PENDING`, после срока — `EXPIRED`. После восстановления брокера отправка повторяется. Kafka-топики: `payment.requests.v1` и `payment.results.v1`; ключ — `booking_id`. Payment-service использует отдельную SQLite-БД на Docker volume для дедупликации.

`PAYMENT_MODE=disabled docker compose up -d --build` отключает `/pay` с ответом `503 PAYMENTS_UNAVAILABLE`. После смены режима пересоздайте backend: `docker compose up -d --force-recreate backend`.

## Данные и миграции

При запуске backend автоматически выполняется `alembic upgrade head`. С хоста Python и PostgreSQL не требуются. Ручной запуск миграции при необходимости: `docker compose run --rm backend alembic upgrade head`.

Полный сброс тестовых данных удаляет пользователей, комнаты, брони и технические события. Он разрешён только при `APP_ENV=development|test` и явном подтверждении:

```bash
docker compose exec -e CONFIRM_TEST_DATA_OPERATION=yes backend python -m app.seed reset-test-data
```

Скрипт после очистки снова создаёт начальные комнаты и учётные записи. Для полного удаления Docker volumes используйте обычные команды Compose только если это действительно нужно.

Для очистки через API авторизуйтесь как ADMIN и отправьте `POST /api/test-data/reset` с Bearer-токеном и телом `{"confirm":"reset-test-data"}`. Метод доступен при `TEST_MODE=true` и `APP_ENV=development` или `test`, возвращает `204` и выполняет очистку и восстановление начальных данных в одной транзакции. Все прежние токены становятся недействительными: после сброса войдите заново с учётными данными из `.env`. Запускайте сброс после завершения тестов и обработки платежей; отдельные данные Kafka и payment-service он не очищает.

## Тестирование

Backend тесты расположены отдельно в `tests/`. Для локального запуска нужны Python 3.12, зависимости `backend/requirements.txt`, `pytest` и `httpx`:

```bash
pip install -r backend/requirements.txt pytest httpx
pytest -q tests --basetemp .pytest_tmp
```

При работающем базовом стеке можно проверить локаторы и встроенные ошибки полей в Chromium без изменения данных:

```bash
pip install playwright
playwright install chromium
python tests/ui_validation_smoke.py
```

## Локаторы UI

У интерактивных полей, кнопок и сообщений есть `data-testid`. Повторяющиеся элементы выбирайте через родителя: `room-card-{id}` → `room-book-button`, `booking-card-{id}` → `booking-status`/`pay-button`/`cancel-button`, `room-editor-{id}` → `room-edit-*`. Формы: `auth-form`, `booking-form`, `room-create-form`, `room-edit-form-{id}`. Ошибки полей имеют отдельные селекторы с суффиксом `-error` (например, `booking-date-error`), ошибки запроса без привязки к полю — `form-error` внутри соответствующей формы.

Все формы используют `noValidate`: сообщения выводятся в интерфейсе под каждым неверным полем, с `role="alert"`, `aria-invalid` и `aria-describedby`.

Тесты используют временную SQLite-БД, поэтому проверяют API/доменную логику, но не транзакционную гарантию `SELECT FOR UPDATE` и не Kafka интеграцию. Для этих сценариев нужен Docker/PostgreSQL/Redpanda. Тестовый дизайн приведён в `tests/TEST_DESIGN.md`.

## Правила API

Все защищённые методы используют Bearer JWT. USER видит только свои брони, ADMIN — все брони и управление комнатами. Дата брони — будний день от завтра до сегодня +14 дней по Europe/Moscow; время 09:00–21:00, старт с шагом 30 минут. Соседние слоты допустимы, пересечения одной комнаты — нет. Публичного API для изменения часов нет; `Clock` внедряется в тестах через `app.domain.clock`.

`DELETE /api/rooms/{id}` доступен только ADMIN: возвращает `204` без тела и отключает комнату (`is_active=false`). Повторный DELETE возвращает `204`, неизвестный ID — `404 ROOM_NOT_FOUND`. Брони сохраняются; USER не видит отключённую комнату и не может создать для неё новую бронь. ADMIN может проверить состояние через `GET /api/rooms/{id}` или `GET /api/rooms?include_inactive=true`.
