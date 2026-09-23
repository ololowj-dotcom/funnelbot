# Deploy and operate

How to run funnelbot on a server, keep it healthy, update it and back it up.

> Русская версия: [ru/deploy.md](ru/deploy.md)

## Choosing a server

funnelbot is light: one small Python process and one SQLite file.

- **Size:** 1 vCPU and 512 MB of RAM are enough for thousands of customers.
- **System:** Ubuntu 22.04 or newer, Debian 12, or another current Linux with `systemd`. The one-command installer supports the apt, dnf and yum families.
- **Network:** outgoing internet access only. **No domain, no HTTPS, no open ports, no webhooks.** The bot asks Telegram for updates ("long polling").
- **Location:** anywhere Telegram is reachable from. If your hosting blocks or throttles Telegram, choose another region or provider.

## Option 1: the one-command installer (recommended)

On a fresh server, as root (or with `sudo`):

```bash
curl -fsSL https://raw.githubusercontent.com/ololowj-dotcom/funnelbot/main/install.sh | sudo bash
```

It installs Python and git if needed, puts funnelbot into `/opt/funnelbot`, adds `/usr/local/bin/funnelbot` and starts `funnelbot setup`, which asks for the token, creates your funnel in `/opt/funnelbot/bot/` and registers a system service that starts on boot and restarts after crashes.

Useful variables for the installer: `FUNNELBOT_NO_SETUP=1` (install only), `FUNNELBOT_PREFIX=/srv/funnelbot` (another folder), `FUNNELBOT_REF=v1.0.0` (a specific version).

### Everyday commands

```bash
systemctl status funnelbot        # is it running?
journalctl -u funnelbot -f        # live log (Ctrl+C to leave)
systemctl restart funnelbot       # restart
funnelbot doctor -f /opt/funnelbot/bot/funnel.yaml   # check token, channel rights, payment keys
funnelbot link -f /opt/funnelbot/bot/funnel.yaml     # print the bot link
```

Editing `funnel.yaml` needs no restart: run `funnelbot validate -f ...` and press **Reload funnel** in `/admin`. Changes to `.env` or to the `payments:` section need `systemctl restart funnelbot`.

### Updating

Run the same installer command again. It upgrades funnelbot, keeps your funnel, database and `.env`, and restarts the running bot.

## Option 2: Docker

```bash
git clone https://github.com/ololowj-dotcom/funnelbot && cd funnelbot
docker compose run --rm funnelbot init /data --token 123456789:AAH... --lang ru
docker compose up -d
docker compose run --rm funnelbot link -f /data/funnel.yaml
```

Your funnel, `.env` and database live in `./bot`. Logs: `docker compose logs -f`. Update: `git pull && docker compose up -d --build`.

## Option 3: by hand

```bash
python3 -m venv /opt/funnelbot/venv
/opt/funnelbot/venv/bin/pip install "git+https://github.com/ololowj-dotcom/funnelbot"
/opt/funnelbot/venv/bin/funnelbot init /opt/funnelbot/bot --token 123456789:AAH...
/opt/funnelbot/venv/bin/funnelbot install-service -f /opt/funnelbot/bot/funnel.yaml
```

`install-service --print` shows the systemd unit without installing it, if you prefer to place it yourself. Any process manager works: the command that runs the bot is `funnelbot run -f /path/to/funnel.yaml`.

## Backups

Everything worth saving is in one folder: `funnel.yaml`, `.env`, `files/` and `funnelbot.db` (customers, orders, access).

A safe copy of the database while the bot runs:

```bash
sqlite3 /opt/funnelbot/bot/funnelbot.db ".backup '/root/backups/funnelbot-$(date +%F).db'"
```

Run it daily from cron (`crontab -e`): `0 4 * * * sqlite3 ... `. Copy the backups off the server. **Restoring an old database is dangerous for access dates**: customers who paid after the backup were not recorded, and funnelbot will alert you about payments it cannot match. Prefer restoring the latest backup.

## Moving to another server

1. Stop the old bot: `systemctl stop funnelbot`.
2. Copy the whole `bot` folder (including `.env` and `funnelbot.db`) to the new server.
3. Install funnelbot there and run `funnelbot install-service -f .../funnel.yaml`.

Never run the same bot token on two servers at once: Telegram accepts only one polling connection and both would misbehave.

## Security checklist

- `.env` holds the token and payment keys. Keep it readable only by the service user (`chmod 600 .env`) and never commit it. The generated `.gitignore` already excludes it.
- If the token leaks, send `/revoke` to @BotFather, put the new token into `.env` and restart.
- Keep the bot's rights in channels minimal: invite users and ban users.
- Add only trusted people to the manager chat: they can approve manual payments.
- Keep the server updated (`apt update && apt upgrade`) and use SSH keys instead of passwords.

## Uninstall

```bash
systemctl disable --now funnelbot && rm /etc/systemd/system/funnelbot.service
rm -rf /opt/funnelbot /usr/local/bin/funnelbot
```

Save the `bot` folder first if you want to keep your data.
