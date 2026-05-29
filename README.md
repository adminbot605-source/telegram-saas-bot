# Telegram SaaS Bot — @zarabot_botbot

Production-ready SaaS бот для управления доступом к Telegram-группам и каналам.

## Архитектура

```
Telegram → Nginx (SSL + rate limit) → aiohttp webhook → Aiogram 3
                                                       ↓
                               AccessCheckMiddleware (Redis O(1))
                                    ↓                    ↓
                              Нет доступа?          Есть доступ?
                         asyncio.create_task()    → handler()
                           bot.delete_message()
```

## Быстрый старт

```bash
# 1. Настройте домен в .env
WEBHOOK_HOST=https://your-domain.com

# 2. SSL-сертификаты в nginx/ssl/fullchain.pem + privkey.pem

# 3. Запуск
make up && make logs
```

## Команды

| Команда | Описание |
|---------|----------|
| `make up` | Запуск всех сервисов |
| `make down` | Остановка |
| `make logs` | Логи |
| `make migrate` | Применить миграции |
| `make health` | Проверка /health |
| `make deploy` | git pull + rebuild |

## Бот-команды

- `/start` — Главное меню + реферальный код из deep link
- `/owner` — Панель владельца группы
- `/creator` — Суперадмин (только CREATOR_USER_ID=5790665502)
- `/access` — Мои активные доступы
- `/referral` — Реферальная программа

## Функционал

### Контроль доступа (главная функция)
- **Redis SET** — O(1) проверка `SISMEMBER` на каждое сообщение
- **fire-and-forget** — `asyncio.create_task(delete_message)` не блокирует обработчик
- 3 retry с backoff при ошибке удаления
- Telegram-администраторы кэшируются 120 сек (`get_chat_administrators`)
- Кэш прогревается при первом сообщении, обновляется фоном каждые 30 мин

### Панель владельца `/owner`
- Включение/выключение контроля доступа
- Выдача доступа вручную (срочный/бессрочный)
- Отзыв доступа
- Создание тарифов
- Просмотр заявок + approve/reject
- Статистика: доступы, платежи, удалённые сообщения, кэш
- Рассылка участникам с доступом
- Настройки: приветствие, антифлуд, антиспам

### Панель создателя `/creator`
- Глобальная статистика
- Все платежи системы
- Выдача/отзыв доступа в любую группу
- Глобальная рассылка всем пользователям
- Сброс Redis-кэша всех групп
- Поиск пользователя по ID или @username

### Платежи
- Пользователь выбирает тариф → загружает фото/документ чека
- Владелец + Создатель получают уведомление с кнопками Approve/Reject
- Approve → авто-выдача доступа + обновление Redis + уведомление пользователю
- Reject → уведомление с причиной
- Заявки старше 7 дней автоматически переводятся в expired

### Тарифы
- Срочные (любое кол-во дней) или бессрочные
- Реквизиты оплаты (карта/СБП/ЮMoney) + QR-код
- Разные тарифы для каждой группы

### Реферальная система
- Авто-генерация кода при регистрации
- Deep link: `t.me/zarabot_botbot?start=ref_{code}`
- Бонус: +7 дней за каждого платящего реферала
- Статистика: кол-во рефералов, суммарный бонус

### Уведомления (APScheduler)
- Напоминание за 72ч, 24ч, 3ч до истечения
- Авто-отзыв просроченных (каждые 5 мин)
- Restrict в Telegram при истечении
- Плановые посты с авто-публикацией (каждую мин)

## Redis-ключи

```
access:group:{id}:users   → SET авторизованных user_id
access:group:{id}:admins  → SET admin user_id
access:group:{id}:loaded  → флаг прогрева кэша (TTL 1ч)
throttle:{user_id}        → антифлуд
stats:deleted:{group_id}  → счётчик удалённых в группе
stats:deleted:total       → глобальный счётчик
```

## PostgreSQL-схема

- `users` + `groups` + `subscriptions` + `scheduled_posts` — базовые
- `tariffs` — тарифы per-group
- `payments` — заявки (pending/approved/rejected/expired)
- `user_access` — активные доступы (expires_at=NULL → бессрочно)
- `referrals` + `referral_codes` — реферальная система

## Производительность (100k+ пользователей)

- **uvloop** — до 2x быстрее asyncio
- **Redis pipeline** — batch-прогрев кэша
- **PostgreSQL**: max_connections=200, shared_buffers=256MB
- **Nginx**: 4096 connections/worker, keepalive 64, rate limiting
- **fire-and-forget** delete — не блокирует основной поток

## Деплой на Railway

```toml
# railway.toml уже настроен
healthcheckPath = "/health"
```

Добавьте переменные окружения из `.env`, укажите `WEBHOOK_HOST` и `POSTGRES_HOST/REDIS_HOST` от Railway-плагинов.
