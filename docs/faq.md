# FAQ and troubleshooting

> Русская версия: [ru/faq.md](ru/faq.md)

## About funnelbot

### What is funnelbot?

A free, open source, self-hosted Telegram bot for selling. You build the conversation (steps, buttons, prices) with buttons inside Telegram, or describe it in one YAML file; the bot takes payments (Telegram Stars, cards, YooKassa, Crypto Pay, manual transfer) and delivers the purchase: access to a private channel for a period, a digital product, or a request to a manager. The owner manages it with buttons in Telegram.

### What can I sell with it?

Paid Telegram channel or chat subscriptions, online courses, PDF guides and templates, consultations and any service that ends with "a manager contacts the customer". It is a good fit for experts, course authors, communities and small shops.

### How is it different from hosted funnel-bot builders?

It is free, runs on your server, keeps customers and payment records with you, has no per-customer or monthly fee, and you build the funnel in a button-based builder inside Telegram itself; the result is a plain text file you can version and copy. It is not a drag-and-drop canvas.

### Do I need to program?

No. You build the funnel with buttons in the bot (`/admin` → **Build the funnel**). If you prefer a text file, the same funnel is a readable YAML file, and `funnelbot validate` explains any mistake in plain words.

### Do I need a domain, HTTPS or open ports?

No. The bot connects out to Telegram. Any small server with internet access will do, or even your own computer while you try it.

### Does it work in Russian and English?

Yes. Every built-in message, for customers and for the admin panel, exists in both. Russian is the default; set `bot.language: en` for English. You write your own funnel texts in any language.

### Is there automatic subscription renewal?

No. Access is bought for a period; before it ends the customer gets a reminder with a **Renew access** button. Telegram's recurring Stars subscriptions are not implemented.

### Is it safe to sell digital goods with methods other than Stars?

Telegram's Bot Developer Terms require Stars for digital goods and services. You may add other methods at your own risk; `funnelbot validate` warns you. See [Payments](payments.md).

## Setup problems

### `funnelbot setup` says Telegram did not accept the token

Copy the token again from @BotFather (the whole line, with the colon). If you regenerated it with `/revoke`, use the new one. Check that the server can reach `api.telegram.org`: `curl -sS https://api.telegram.org` should answer.

### The bot does not answer

1. `systemctl status funnelbot`: is it running? `journalctl -u funnelbot -n 50` shows the reason if not.
2. `Conflict: terminated by other getUpdates request` in the log means the same token is running elsewhere (another server, your computer, an old container). Stop the other copy.
3. Run `funnelbot doctor -f /opt/funnelbot/bot/funnel.yaml`.

### The link printed by setup says "Nothing to claim"

The bot already has an administrator (perhaps you, from an earlier try), or the code in the link is old. Run `funnelbot link -f ...` for the current link. If an administrator is already set you do not need it: send `/admin`. To add yourself in another way, put your id into `ADMIN_ID` in `.env` (send `/id` to the bot to see it) and restart.

### `funnelbot validate` shows errors

Each line says where the problem is (`steps.welcome.buttons[0][1].goto`) and what is wrong, often with a hint ("did you mean 'offer'?"). Fix them all and run it again. While the file has errors the running bot keeps using the last good version.

### "environment variable X is not set"

The funnel refers to `${X}` but `.env` (next to `funnel.yaml`) has no value for it. Add `X=value` to `.env`.

## Selling access to a channel

### The customer paid but cannot get into the channel

They must press **Request to join** on the link the bot sent, from the same Telegram account that paid. In `/admin` open **Find user** and check that the access is "active". Run **Health check**: the bot must be an administrator of the channel with the rights to invite and to ban users.

### `/id` in my channel gets no reply

The bot must already be an administrator of the channel, and you must post `/id` **in the channel**, not in a chat with the bot.

### Customers were not removed when their time ended

Look at the alerts in your manager chat or private chat with the bot. Usually the bot lost its "Ban users" right, or the person is an administrator of the channel (bots cannot remove those). Fix the cause; funnelbot keeps retrying and completes the removal.

### Can one product open two channels?

Yes: list two `channel` items in `access`. See [Private channel access](private-channel-access.md).

## Payments

### The payment went through but the bot did nothing

Stars and card payments are confirmed by Telegram instantly. For YooKassa and Crypto Pay the bot checks every `poll_seconds` (20 by default) and the customer can press **I have paid** for an instant check. If nothing happens, run `funnelbot doctor` to test the keys and look at the log. If money arrived for an order the bot does not know, you receive an alert with the details.

### How do I test payments without spending money?

Turn on test mode (`/admin` → **Build the funnel** → **Payments and language**), and use the **Test payment** button on a product card (administrators only). For cards and YooKassa use their test modes; for crypto use @CryptoTestnetBot with `api_base: https://testnet-pay.crypt.bot/api`. `funnelbot preview` rehearses everything in the terminal.

### How do I refund?

`/admin` → **Payments** → the order → **Refund**. Stars return automatically; for other methods, return the money in that service.

### Prices show "500 ⭐" but I want Rubles too

Give the product several prices, for example `prices: {XTR: 500, RUB: 4900}`, and enable both methods. The customer then chooses a method.

## Editing the funnel

### Can I build the funnel without editing a file?

Yes. Send `/admin` and press **🛠 Build the funnel**: steps, buttons, products, reminders, questions and private-channel access are all created with buttons. See [Building a funnel in Telegram](funnel-builder.md).

### I edited funnel.yaml by hand and my comments disappeared

The builder rewrites the file in a standard layout each time it saves, which drops hand-written comments. The previous version is kept as `funnel.yaml.bak`. If you edit by hand and want to keep comments, do not use the builder for that funnel.

### How do I change a text, a price or a button?

Edit `funnel.yaml`, run `funnelbot validate`, press **Reload funnel** in `/admin`. No restart needed. Changes to `.env` or to `payments:` need a restart.

### How do I add a new product?

Add an entry under `products:` and offer it with a button `{text: Buy, pay: product_id}`. See [Configuration](configuration.md).

### The coloured buttons or custom emoji do not show

They require a recent Telegram app on the customer's side. Older apps show ordinary buttons; nothing breaks.

### I want to ask the customer for their email or phone

Add a step with `ask: {key: email, type: email}` and `next: <step>`. The answer is saved, usable as `{email}` in texts and exported with `funnelbot export`.

## Data and privacy

### Where is my data?

In `funnelbot.db` (SQLite) next to `funnel.yaml`. Back it up: see [Deploy and operate](deploy.md).

### How does a customer delete their data?

`/deleteme` in the bot, with a confirmation. Administrators can do it from the customer card. Personal data is erased, access ends, and payment records remain for accounting linked only to a Telegram id.

### Which messages can customers refuse?

`/stop` turns off promotional messages (nudges and broadcasts). Notices about their own access (reminders, expiry) still arrive. `/resume` turns promotions back on.

## Still stuck?

Run `funnelbot doctor`, read the last lines of `journalctl -u funnelbot`, and open an issue on GitHub with the output (remove tokens first).
