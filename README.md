# funnelbot — self-hosted Telegram sales-funnel bot with payments

**funnelbot** turns one YAML file into a Telegram bot that walks a customer through a sales funnel, takes payment and then delivers what was bought: **access to a private channel or group for a period of time**, a **digital product** (text and files), or a **request to a manager**. It is free, open source (MIT) and runs on your own server, so there is no monthly fee to a hosted bot builder and your customers stay yours.

> Русская версия: [README.ru.md](README.ru.md)

**In one line:** sell paid Telegram channel subscriptions, courses, guides and consultations through a bot, accept **Telegram Stars, bank cards, YooKassa and crypto (Crypto Pay / @CryptoBot)**, and manage everything **with buttons inside Telegram**.

## What you get

- **Build the funnel inside Telegram.** In the admin panel press **Build the funnel** and create steps, buttons (with colours), products, prices, reminders, questions and paid access to a private channel, all with buttons and short messages. No file editing, no code. See [Building a funnel in Telegram](docs/funnel-builder.md).
- **Funnel as a file, if you prefer.** Everything the builder makes is a readable `funnel.yaml` that you can also edit by hand, keep in git and copy to another bot. `funnelbot validate` explains every mistake in plain words.
- **Everything works with buttons.** The customer taps buttons. You, the owner, send `/admin` and get a control panel: statistics, broadcasts, payments and refunds, find a customer, give or take away access, health check. No commands to memorise.
- **Speaks Russian and English.** Every message the bot sends, to customers and to you in the admin panel, exists in both languages. Russian is the default; set `bot.language: en` for English. You can override any built-in phrase in `funnel.yaml`.
- **Coloured buttons.** Blue, green and red buttons and custom emoji on buttons (Bot API 9.4). Pay buttons are green by default.
- **Five ways to pay**, mixable per product: Telegram Stars, bank cards through a Telegram payment provider, YooKassa payment links, Crypto Pay (USDT, TON and more), and manual transfer with a screenshot that a manager approves with one tap.
- **Paid access to a private channel or group.** The bot hands out a one-time-approval join link, lets in only paying customers, warns them 3 and 1 days before the end, removes them when time is up (and keeps retrying if Telegram says no), and extends access on renewal.
- **Digital products.** Send text, a PDF, an archive or any file right after payment. Files are uploaded once and reused.
- **Manager requests.** Paid orders and "ask a question" buttons land in your manager chat as a card with the customer, their answers and the order.
- **Reminders that sell.** "Still thinking?" nudges after 3 hours, 24 hours or whatever you choose. They stop once the customer buys or opens /stop.
- **Try before you launch.** `funnelbot preview` lets you click through the whole funnel in the terminal, with fake payments and time travel (`:tick 30d` shows the expiry reminders and removal).
- **Simple to host.** One command on a fresh Linux server. No domain, no HTTPS, no open ports, no webhooks: the bot polls Telegram.
- **Honest about the rules.** Telegram requires Stars for digital goods and services. funnelbot puts Stars first, warns you when a digital product is sold by other methods, and ships the mandatory `/paysupport` and refund tools. See [Payments](docs/payments.md).

## Quick start (about 10 minutes)

You need two things: a Telegram account and a small Linux server (any VPS with Ubuntu 22.04+ or Debian 12+, 512 MB of RAM is plenty). No server yet? You can also run it on your own computer, see [Getting started](docs/getting-started.md).

**1. Create the bot.** In Telegram open [@BotFather](https://t.me/BotFather), send `/newbot`, pick a name and a username ending in `bot`. BotFather replies with a **token** like `123456789:AAH...`. Keep it secret.

**2. Install on the server.** Connect by SSH and run one command:

```bash
curl -fsSL https://raw.githubusercontent.com/ololowj-dotcom/funnelbot/main/install.sh | sudo bash
```

The installer sets up Python, installs funnelbot and starts a guided setup: it asks for the token (and checks it right away), the language, and offers to run the bot in the background and on every reboot.

**3. Become the administrator.** At the end the setup prints a link. Open it in Telegram and press Start: you are now the bot's administrator.

**4. Open the panel.** Send `/admin` to your bot. Everything else is buttons.

**5. Build your funnel.** In the panel press **🛠 Build the funnel**: add a product (name, price in Stars, and what the customer gets, for example access to your private channel for 30 days), write the steps, join them with buttons and try it with **See it as a customer**. The full walkthrough is in [Building a funnel in Telegram](docs/funnel-builder.md); connecting the channel is in [Private channel access](docs/private-channel-access.md). Prefer a file? Edit `/opt/funnelbot/bot/funnel.yaml` and press **Reload funnel**.

Try a complete demo funnel in the terminal, without any Telegram:

```bash
funnelbot init demo --sample
funnelbot preview -f demo/funnel.yaml
```

## A funnel in 20 lines

```yaml
bot:
  language: en
  admins: ["${ADMIN_ID}"]
payments:
  stars: true
products:
  club:
    title: Private club
    description: Closed channel with weekly materials.
    prices: {XTR: 500}
    access:
      - channel: {chat: -1001234567890, days: 30, remind_days: [3, 1]}
start: welcome
steps:
  welcome:
    text: "Hi, <b>{first_name}</b>! Join the club?"
    buttons:
      - [{text: Join for 500 ⭐, pay: club, style: success}]
    nudges:
      - after: 3h
        text: "Still thinking? The club is open."
        buttons:
          - [{text: Join, pay: club, style: success}]
```

That is a complete funnel: the customer pays 500 Stars, receives a join link, is approved into the channel for 30 days, gets reminders before the end and an option to renew. The full list of options is in [Configuration](docs/configuration.md).

## Ready-made examples

The [examples](examples) folder holds complete funnels you can copy and adapt:

- [paid-channel.yaml](examples/paid-channel.yaml): a paid private channel with reminders and renewal;
- [course-with-file.yaml](examples/course-with-file.yaml): a digital product paid by Stars or YooKassa, with an email question for the receipt;
- [consultation-request.yaml](examples/consultation-request.yaml): a paid service that ends with an order card for your manager.

## Commands

| Command | What it does |
|---|---|
| `funnelbot setup` | Guided setup: token, language, admin, background service |
| `funnelbot init [folder]` | Create `funnel.yaml`, `.env` and a sample product file |
| `funnelbot validate` | Check the funnel and print how the steps connect |
| `funnelbot preview` | Click through the funnel in the terminal with fake payments and time travel |
| `funnelbot doctor` | Check the token, the bot's rights in your channels and payment credentials |
| `funnelbot run` | Start the bot |
| `funnelbot install-service` | Run in the background and on boot (systemd) |
| `funnelbot link` | Print the bot link and the one-tap "become administrator" link |
| `funnelbot export leads.csv` | Save all customers and their answers |

Inside Telegram the owner uses `/admin`. Customers can use `/help`, `/terms`, `/paysupport`, `/deleteme`, `/stop` and `/resume`.

## Documentation

- [Getting started](docs/getting-started.md): from zero to a running bot, server or your own computer
- [Building a funnel in Telegram](docs/funnel-builder.md): steps, buttons, products, reminders and channel access with buttons
- [Configuration reference](docs/configuration.md): every key of `funnel.yaml`
- [Payments](docs/payments.md): Stars, cards, YooKassa, Crypto Pay, manual transfer, Telegram's rules
- [Private channel access](docs/private-channel-access.md): connect a channel, how access, reminders and removal work
- [Admin panel](docs/admin-panel.md): everything the owner can do with buttons
- [Deploy and operate](docs/deploy.md): server, Docker, updates, backups, logs
- [FAQ and troubleshooting](docs/faq.md)

## Good to know

- **Where the data lives.** One SQLite file (`funnelbot.db`) next to `funnel.yaml`. Back it up together with `.env`.
- **Secrets.** Tokens and keys go into `.env` and are referenced as `${NAME}` in the YAML. Never commit `.env` (the generated `.gitignore` already excludes it).
- **Privacy.** Customers can erase their data with `/deleteme`; you can do it for them from the panel. Payment records stay for accounting, linked only to a Telegram id.
- **Status.** The project is covered by automated tests (funnel logic, payments, access lifecycle, the panel, the installer, and a fake Telegram server that exercises the real bot library). Real money and real channels can only be tried by you: run `funnelbot doctor`, turn on `bot.test_mode` (a free test payment button for admins) and buy your own product first.
- **Limits.** funnelbot is a funnel engine, not a visual builder, a website or a CRM. Telegram Stars subscriptions with automatic renewal are not implemented: access is bought for a period and renewed by the customer with one tap after a reminder.

## Requirements

Python 3.10+ (installed for you by `install.sh`), the `aiogram`, `aiohttp` and `PyYAML` libraries. Works on Linux, macOS and Windows for development; the one-command installer and the systemd service are Linux only. Docker is supported: see [Deploy and operate](docs/deploy.md).

## Contributing

Issues and pull requests are welcome. Run `pip install -e ".[dev]"`, then `ruff check src tests` and `pytest`.

## License

MIT
