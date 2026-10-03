# Деплой

Боевой стенд — три контейнера на одном сервере (`deploy/docker-compose.prod.yml`):

| Контейнер | Что делает | Наружу |
|---|---|---|
| `web` | Caddy: раздаёт сборку фронта, проксирует `/api` на бэкенд, сам получает и продлевает сертификат | 80, 443 |
| `backend` | FastAPI + планировщик (цены, ставки, прогрев кэша), один воркер | нет |
| `db` | Postgres 18 | нет |

Страница и API — один домен: фронт ходит на `/api`, Caddy срезает префикс.
Поэтому cookie входа работают без CORS, а `ALLOWED_ORIGINS` — это сам сайт.

**Где что делается.** Разбор PDF, сбор раскрытий с e-disclosure и проверка
отчётов — на рабочей машине: там LLM-ключи, Playwright и папка с отчётами. На
сервер приезжает готовая база (`deploy/push-data.sh`). Сервер только показывает
данные и раз в день обновляет цены.

## Сервер

- Россия (152-ФЗ: учётные записи посетителей — персональные данные).
- 2 ядра, 2–4 ГБ памяти, 20 ГБ диска. Бэкенд с прогретым кэшем — около 300 МБ.
- Ubuntu 24.04 / Debian 13, Docker с плагином compose.
- DNS: A-запись домена → IP сервера. Без неё Caddy не получит сертификат.
- Открыты только 22, 80, 443 (`ufw allow OpenSSH; ufw allow 80; ufw allow 443`).

## Первая выкатка

```bash
# на сервере
sudo mkdir -p /opt/graham && sudo chown "$USER" /opt/graham
git clone https://github.com/<repo>.git /opt/graham
cd /opt/graham/deploy
cp env.prod.example .env.prod && chmod 600 .env.prod
# заполнить .env.prod: домен, пароль базы, SECRET_KEY, почта, токен T-Invest
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f backend
```

Бэкенд при старте сам применяет миграции — пустая база получает схему.

```bash
# на рабочей машине — данные
SERVER=deploy@сервер ./deploy/push-data.sh

# на сервере — администратор
docker compose -f docker-compose.prod.yml --env-file .env.prod exec backend python -m scripts.create_admin
```

## Обновление

Код:

```bash
cd /opt/graham && git pull
cd deploy && docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

Данные (после разбора и проверки отчётов локально):

```bash
SERVER=deploy@сервер ./deploy/push-data.sh
```

Скрипт выгружает всё, кроме таблиц входа (`users`, `user_sessions`,
`auth_tokens`): учётные записи посетителей живут только на сервере и при
выкатке данных не трогаются. Перед заменой на сервере делается бэкап.
Порядок — сначала код, потом данные: схема должна совпадать.

## Бэкапы

```cron
15 4 * * *  /opt/graham/deploy/backup.sh >> /var/log/graham-backup.log 2>&1
```

Хранятся последние 14 в `~/graham-backups`. Копия на том же диске от
потери сервера не спасает: задайте `BACKUP_REMOTE` (адрес для rsync) в
окружении cron.

Восстановление:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T db \
  pg_restore -U graham -d graham_analyzer --clean --if-exists --no-owner < файл.dump
docker compose -f docker-compose.prod.yml --env-file .env.prod restart backend
```

## Проверка на своей машине

Тот же стенд без домена и сертификата, сайт на http://localhost:8080:

```bash
cd deploy
cp env.prod.example .env.prod
# SITE_ADDRESS=:80, ALLOWED_ORIGINS и PUBLIC_SITE_URL=http://localhost:8080,
# COOKIE_SECURE=false, HTTP_PORT=8080, HTTPS_PORT=8443, пароли — любые
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

## Перед открытием

- [ ] `DEBUG=false`, `COOKIE_SECURE=true`, адреса — `https://домен`
- [ ] Пароль базы и `SECRET_KEY` — случайные, `.env.prod` с правами 600
- [ ] Почта настроена (`python -m scripts.check_mail адрес` в контейнере) —
      иначе регистрацию не открывать
- [ ] Данные оператора в `frontend/src/legal/operator.ts`, уведомление в
      Роскомнадзор подано (docs/PERSONAL_DATA.md)
- [ ] Бэкап по cron и копия вне сервера
- [ ] Администратор создан, вход проверен
