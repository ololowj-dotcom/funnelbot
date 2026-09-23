# Getting started

This page takes you from nothing to a working sales bot. No programming is needed. Allow about 10 minutes.

> Русская версия: [ru/getting-started.md](ru/getting-started.md)

## What you need

1. **A Telegram account.** You will create the bot and manage it from there.
2. **A place to run the bot 24/7.** The easiest is a small Linux server (a "VPS"): Ubuntu 22.04 or newer, or Debian 12, with 512 MB of RAM. Any hosting provider works. You do **not** need a domain, HTTPS or open ports. If you only want to try the bot, your own computer is enough (see [Run it on your own computer](#run-it-on-your-own-computer)).

## Step 1. Create the bot in Telegram

Every Telegram bot is created through a bot called BotFather.

1. Open Telegram and search for **@BotFather** (it has a blue check mark), or open <https://t.me/BotFather>.
2. Send `/newbot`.
3. BotFather asks for a **name** (shown to customers, for example "My Club") and a **username** (must end with `bot`, for example `my_club_bot`).
4. BotFather answers with a message containing the **token**, a line like `123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw`. Copy it. **Anyone with this token controls your bot, so never post it publicly.** If it leaks, send `/revoke` to BotFather to get a new one.

Optional but nice: send `/setuserpic` to give the bot a picture and `/setdescription` for the text customers see before pressing Start.

## Step 2. Install funnelbot on the server

Connect to the server over SSH (your hosting provider shows the address and password or key). Then run one command:

```bash
curl -fsSL https://raw.githubusercontent.com/ololowj-dotcom/funnelbot/main/install.sh | sudo bash
```

If you are already `root`, `sudo` is not needed. The installer:

- installs Python and git if they are missing (Debian, Ubuntu, Fedora, CentOS/RHEL families);
- installs funnelbot into `/opt/funnelbot` and adds the `funnelbot` command;
- starts the guided setup.

## Step 3. Answer the setup questions

The setup asks three things:

1. **The token** from BotFather. It is checked with Telegram immediately, so a typo is caught on the spot and you can paste it again.
2. **The language** of the bot: `ru` (default) or `en`.
3. **Who manages the bot.** Press Enter to use the one-tap link (easiest), or type your Telegram user id.

Then it offers to **run the bot in the background and start it on every server reboot**. Answer `y`.

At the end it prints a link like `https://t.me/my_club_bot?start=claim_...`.

## Step 4. Become the administrator

Open the printed link in Telegram and press **Start**. The bot answers "You are now the administrator" with a button that opens the control panel. The link works only until someone claims the bot, so it cannot be used by strangers afterwards.

From now on send `/admin` to your bot any time to open the control panel: statistics, broadcasts, payments, customers, health check. Everything is buttons.

## Step 5. Build your funnel in the bot

The setup created a small starter funnel in `/opt/funnelbot/bot/`. Open your bot and press Start: it greets you and tells you where to go next.

Now build your own. Send `/admin` and press **🛠 Build the funnel**. With buttons and short messages you can:

- create a **product** (name, price, and what the customer gets: access to a private channel for some days, a message with a file, or a request to a manager);
- write **steps** (the messages customers see) and add **buttons** to them, in blue, green or red;
- add **reminders**, **questions** (email, phone) and pictures;
- press **▶️ See it as a customer** to try it.

The full walkthrough with a 5-minute example (a paid private channel) is in [Building a funnel in Telegram](funnel-builder.md).

Everything you build is saved in `/opt/funnelbot/bot/`:

| File | What it is |
|---|---|
| `funnel.yaml` | Your funnel. Readable, and you may also edit it by hand |
| `funnel.yaml.bak` | The previous version, kept automatically |
| `.env` | Secrets: the token and later payment keys. Never share it |
| `funnelbot.db` | Appears after the first start: customers, orders, access |

If you prefer a text file, edit it (`nano /opt/funnelbot/bot/funnel.yaml`), run `funnelbot validate -f /opt/funnelbot/bot/funnel.yaml`, then press **Reload funnel** in `/admin`. To rehearse a complete demo funnel in the terminal, including payments and the passing of time: `funnelbot init demo --sample` and `funnelbot preview -f demo/funnel.yaml`.

## Step 6. Connect payments and your private channel

- **Telegram Stars** work right away, no account needed, and are on by default. Prices are in Stars.
- Cards, YooKassa, crypto and manual transfer need keys from those services: [Payments](payments.md).
- To sell access to a private channel, connect it: [Private channel access](private-channel-access.md).

Before real customers arrive, turn on test mode (`/admin` → **Build the funnel** → **Payments and language** → **Turn on test mode**), buy your own product with the free test button, then check `/admin` → **Health check**. Turn test mode off before you launch.

## Run it on your own computer

Handy for trying the bot. It only works while the computer is on and online.

1. Install Python 3.10 or newer from <https://www.python.org/downloads/> (on Windows tick "Add python.exe to PATH").
2. Open a terminal and run:

   ```bash
   python -m pip install "git+https://github.com/ololowj-dotcom/funnelbot"
   funnelbot setup
   ```

3. Start the bot and leave the window open:

   ```bash
   funnelbot run
   ```

## Run it with Docker

```bash
git clone https://github.com/ololowj-dotcom/funnelbot && cd funnelbot
docker compose run --rm funnelbot init /data --token 123456789:AAH... --lang ru
docker compose up -d
docker compose run --rm funnelbot link -f /data/funnel.yaml
```

The last command prints the one-tap "become administrator" link. Your funnel and database live in the `bot/` folder next to `docker-compose.yml`.

## If something does not work

Run `funnelbot doctor`. It checks the token, your channels and payment keys and says in plain words what to fix. More help: [FAQ and troubleshooting](faq.md).
