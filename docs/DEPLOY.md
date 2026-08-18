# Установка на сервер

Пошагово, без предположений о технических знаниях. Всё вместе занимает
примерно час. Если будете нанимать админа — этой страницы ему достаточно.

## Что понадобится

1. **Сервер в России.** Selectel, Timeweb, VK Cloud или Яндекс Облако.
   Берите самый простой: 2 ядра, 4 ГБ памяти, 40 ГБ диска, Ubuntu 24.04.
   Ориентир — 800–1500 ₽ в месяц.
2. **Домен.** Подойдёт поддомен основного сайта, например `dela.garantlc.ru`.
   В настройках домена сделайте A-запись на IP-адрес сервера.
3. **Доступ к хостингу garantlc.ru** — чтобы вставить одну строку кода
   на страницы сайта.

## Шаг 1. Подготовить сервер

Подключитесь к серверу по SSH и выполните:

```bash
# Docker — среда, в которой запускается система
curl -fsSL https://get.docker.com | sh

# Забираем код
git clone https://github.com/hj5v9yw6cs-collab/dolshiki_msk.git /opt/dolshiki
cd /opt/dolshiki
```

## Шаг 2. Настроить

Два файла с настройками.

**`backend/.env`** — параметры приложения:

```bash
cp backend/.env.example backend/.env
nano backend/.env
```

Обязательно поменяйте `ADMIN_TOKEN` на длинную случайную строку.
Сгенерировать: `openssl rand -base64 32`

Впишите домены сайта, чтобы калькулятор с них работал:

```
ADMIN_TOKEN=сюда-длинную-случайную-строку
CORS_ORIGINS=https://garantlc.ru,https://www.garantlc.ru
```

**`deploy/.env`** — домен самой системы:

```bash
cp deploy/.env.example deploy/.env
nano deploy/.env
```

```
DOMAIN=dela.garantlc.ru
```

## Шаг 3. Запустить

```bash
cd /opt/dolshiki/deploy
docker compose up -d
```

Через минуту система будет доступна по адресу `https://dela.garantlc.ru`.
Сертификат HTTPS выпускается автоматически, ничего настраивать не нужно.

Проверить, что всё поднялось:

```bash
docker compose ps
curl https://dela.garantlc.ru/health
```

## Шаг 4. Завести сотрудников

```bash
cd /opt/dolshiki/deploy
docker compose exec app python scripts/create_user.py boss@garantlc.ru "Фёдор Ильин" manager
docker compose exec app python scripts/create_user.py irina@garantlc.ru "Ирина Соколова" lawyer
```

Пароль спрашивается при вводе и в истории команд не сохраняется.
Роли: `manager` — руководитель, видит деньги; `lawyer` — юрист.

Кабинет: `https://dela.garantlc.ru/app/`

## Шаг 5. Поставить калькулятор на сайт

На страницы garantlc.ru, где нужен калькулятор, вставьте две строки:

```html
<div id="garant-calc"></div>
<script src="https://dela.garantlc.ru/embed.js"
        data-target="garant-calc"
        data-policy-url="https://garantlc.ru/policy"></script>
```

Открыть сразу на нужном сценарии: добавьте `data-mode="defects"` для
недостатков отделки или `data-mode="delay"` для просрочки.

Заявки с калькулятора начнут падать в кабинет, во вкладку «Заявки».
Оттуда дело заводится одной кнопкой.

## Шаг 6. Автоматические задачи

```bash
crontab -e
```

Вставьте строки из `deploy/crontab.example`:

```
0 6 * * *  cd /opt/dolshiki/deploy && docker compose exec -T app python scripts/sync_rates.py >> /var/log/dolshiki-cbr.log 2>&1
0 3 * * *  /opt/dolshiki/deploy/backup.sh >> /var/log/dolshiki-backup.log 2>&1
```

Первая обновляет ключевую ставку ЦБ, вторая делает резервную копию базы
в `/var/backups/dolshiki` и удаляет копии старше 30 дней.

**Проверьте бэкап руками сразу после установки:**

```bash
/opt/dolshiki/deploy/backup.sh
ls -la /var/backups/dolshiki
```

Копию стоит забирать и с сервера тоже — если сервер пропадёт, пропадут и
копии на нём. Настройте выгрузку в другое хранилище или скачивайте раз в
неделю вручную.

## Шаг 7. Уведомления в Telegram (необязательно)

Чтобы заявки приходили в Telegram:

1. Напишите `@BotFather`, создайте бота, получите токен.
2. Добавьте бота в чат, узнайте ID чата.
3. Впишите в `backend/.env`:

```
TELEGRAM_BOT_TOKEN=токен-от-BotFather
TELEGRAM_CHAT_ID=id-чата
```

4. `docker compose up -d` — перезапустится с новыми настройками.

Если не настраивать, заявки всё равно сохраняются в базу и видны в кабинете.

## Обновление системы

```bash
cd /opt/dolshiki
git pull
cd deploy
docker compose up -d --build
```

База и правки юриста в конфиге лежат в отдельных томах и при обновлении
не затрагиваются.

## Восстановление из копии

```bash
cd /opt/dolshiki/deploy
docker compose down
mkdir -p /tmp/restore && tar -xzf /var/backups/dolshiki/dolshiki-ДАТА.tar.gz -C /tmp/restore
docker compose run --rm -v /tmp/restore:/restore app sh -c "cp /restore/app.db data/app.db && cp -r /restore/config/. config/"
docker compose up -d
```

## Про базу данных

По умолчанию используется SQLite — вся база лежит в одном файле. При
четырёх сотрудниках и 30 делах в месяц этого достаточно с большим
запасом, а резервное копирование сводится к копированию одного файла.

Если когда-нибудь понадобится PostgreSQL, менять код не нужно: достаточно
прописать в `backend/.env` строку подключения:

```
DATABASE_URL=postgresql+psycopg://пользователь:пароль@адрес:5432/база
```

## Чего в этой сборке нет

Названо честно, чтобы не всплыло при установке:

- **Образ Docker не собирался в среде разработки** — доступ к Docker Hub
  оттуда закрыт. Файлы стандартные и проверены на синтаксис, но первую
  сборку `docker compose up -d --build` вы увидите вживую сами.
- **Почтовых уведомлений нет** — только Telegram. Почта появится, когда
  понадобится отправлять письма клиентам.
- **Мониторинга нет.** Если система упадёт, вы узнаете об этом, когда
  зайдёте. При таком размере это приемлемо, но помните об этом.
