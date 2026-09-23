# Развёртывание и обслуживание

Как запустить funnelbot на сервере, следить за ним, обновлять и делать резервные копии.

> English version: [../deploy.md](../deploy.md)

## Выбор сервера

funnelbot лёгкий: один небольшой процесс Python и один файл SQLite.

- **Размер:** 1 vCPU и 512 МБ памяти хватит на тысячи клиентов.
- **Система:** Ubuntu 22.04 или новее, Debian 12 либо другой современный Linux с `systemd`. Установщик одной командой поддерживает семейства apt, dnf и yum.
- **Сеть:** нужен только исходящий интернет. **Домен, HTTPS, открытые порты и вебхуки не нужны.** Бот сам запрашивает у Telegram обновления («длинный опрос»).
- **Расположение:** где угодно, откуда доступен Telegram. Если хостинг блокирует или замедляет Telegram, выберите другой регион или провайдера.

## Вариант 1: установщик одной командой (рекомендуется)

На чистом сервере от root (или через `sudo`):

```bash
curl -fsSL https://raw.githubusercontent.com/ololowj-dotcom/funnelbot/main/install.sh | sudo bash
```

Он поставит Python и git при необходимости, положит funnelbot в `/opt/funnelbot`, добавит `/usr/local/bin/funnelbot` и запустит `funnelbot setup`: тот спросит токен, создаст воронку в `/opt/funnelbot/bot/` и зарегистрирует системный сервис, который стартует при загрузке и перезапускается после сбоев.

Полезные переменные установщика: `FUNNELBOT_NO_SETUP=1` (только установить), `FUNNELBOT_PREFIX=/srv/funnelbot` (другая папка), `FUNNELBOT_REF=v1.0.0` (конкретная версия).

### Ежедневные команды

```bash
systemctl status funnelbot        # работает ли?
journalctl -u funnelbot -f        # лог в реальном времени (Ctrl+C, чтобы выйти)
systemctl restart funnelbot       # перезапуск
funnelbot doctor -f /opt/funnelbot/bot/funnel.yaml   # проверить токен, права в каналах, ключи оплат
funnelbot link -f /opt/funnelbot/bot/funnel.yaml     # показать ссылку на бота
```

Правка `funnel.yaml` не требует перезапуска: выполните `funnelbot validate -f ...` и нажмите **«Перезагрузить воронку»** в `/admin`. Изменения в `.env` или в разделе `payments:` требуют `systemctl restart funnelbot`.

### Обновление

Выполните ту же команду установщика ещё раз. Он обновит funnelbot, сохранит воронку, базу и `.env` и перезапустит работающего бота.

## Вариант 2: Docker

```bash
git clone https://github.com/ololowj-dotcom/funnelbot && cd funnelbot
docker compose run --rm funnelbot init /data --token 123456789:AAH... --lang ru
docker compose up -d
docker compose run --rm funnelbot link -f /data/funnel.yaml
```

Воронка, `.env` и база лежат в `./bot`. Логи: `docker compose logs -f`. Обновление: `git pull && docker compose up -d --build`.

## Вариант 3: вручную

```bash
python3 -m venv /opt/funnelbot/venv
/opt/funnelbot/venv/bin/pip install "git+https://github.com/ololowj-dotcom/funnelbot"
/opt/funnelbot/venv/bin/funnelbot init /opt/funnelbot/bot --token 123456789:AAH...
/opt/funnelbot/venv/bin/funnelbot install-service -f /opt/funnelbot/bot/funnel.yaml
```

`install-service --print` покажет unit-файл systemd без установки, если хотите положить его сами. Подойдёт любой менеджер процессов: бот запускается командой `funnelbot run -f /путь/к/funnel.yaml`.

## Резервные копии

Всё, что стоит сохранить, лежит в одной папке: `funnel.yaml`, `.env`, `files/` и `funnelbot.db` (клиенты, заказы, доступы).

Безопасная копия базы, пока бот работает:

```bash
sqlite3 /opt/funnelbot/bot/funnelbot.db ".backup '/root/backups/funnelbot-$(date +%F).db'"
```

Запускайте её ежедневно из cron (`crontab -e`): `0 4 * * * sqlite3 ... `. Копируйте резервные копии за пределы сервера. **Восстановление старой базы опасно для дат доступа**: клиенты, заплатившие после копии, в ней не записаны, а funnelbot предупредит о платежах, которые не может сопоставить. Восстанавливайте самую свежую копию.

## Переезд на другой сервер

1. Остановите старого бота: `systemctl stop funnelbot`.
2. Скопируйте всю папку `bot` (включая `.env` и `funnelbot.db`) на новый сервер.
3. Установите там funnelbot и выполните `funnelbot install-service -f .../funnel.yaml`.

Никогда не запускайте один и тот же токен на двух серверах одновременно: Telegram допускает только одно подключение с опросом, и оба бота будут вести себя неправильно.

## Чек-лист безопасности

- В `.env` лежат токен и ключи оплат. Оставьте доступ к нему только пользователю сервиса (`chmod 600 .env`) и не публикуйте. Созданный `.gitignore` уже исключает его.
- Если токен утёк, отправьте `/revoke` в @BotFather, впишите новый токен в `.env` и перезапустите бота.
- Держите права бота в каналах минимальными: приглашать и блокировать пользователей.
- В чат менеджеров добавляйте только доверенных людей: они могут подтверждать ручные платежи.
- Обновляйте сервер (`apt update && apt upgrade`) и входите по SSH-ключам, а не по паролю.

## Удаление

```bash
systemctl disable --now funnelbot && rm /etc/systemd/system/funnelbot.service
rm -rf /opt/funnelbot /usr/local/bin/funnelbot
```

Сначала сохраните папку `bot`, если хотите оставить данные.
