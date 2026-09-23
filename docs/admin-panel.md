# Admin panel

Everything the owner does day to day is in a **control panel inside Telegram**, built from buttons. Open it by sending `/admin` to your bot. Only administrators can use it.

> Русская версия: [ru/admin-panel.md](ru/admin-panel.md)

## Becoming an administrator

Any of these works, and you can combine them:

- **The one-tap link.** `funnelbot setup` (or `funnelbot link`) prints `https://t.me/your_bot?start=claim_...`. Open it and press Start. It works only while the bot has no administrator, so nobody can steal the bot afterwards.
- **Your Telegram id in the config.** Send `/id` to the bot, then put the number in `bot.admins` (or `ADMIN_ID` in `.env`).

## The menu

| Button | What it does |
|---|---|
| **📊 Stats** | Customers (today, this week), buyers and conversion, payments, refunds, waiting orders, active access, revenue per currency (total, 7 days, 24 hours), where customers are now in the funnel, traffic sources |
| **👥 Leads (CSV)** | Sends a spreadsheet of every customer with their answers, source and what they bought. Opens in Excel and Google Sheets |
| **🛠 Build the funnel** | Create and edit steps, buttons, products, reminders, questions and channel access with buttons: [Building a funnel in Telegram](funnel-builder.md) |
| **📣 Broadcast** | Guided message to a group of customers (below) |
| **💳 Payments** | The latest orders. Tap one for details and a **Refund** button |
| **🔎 Find user** | Send an id or @username to open the customer card |
| **🩺 Health check** | Checks the bot's rights in every channel, the payment services, and orders waiting for delivery |
| **🔄 Reload funnel** | Reads `funnel.yaml` again without restarting. If the file has a mistake, the old version keeps running and you see what to fix |

## Broadcast

1. Press **Broadcast**.
2. Send the message you want to deliver, exactly as customers should see it: text, photo, video, voice message or file, with formatting. The bot copies it, so nothing is lost.
3. Choose who receives it. Every button shows how many people that is:
   - **Everyone**, **Buyers**, **Not bought yet**, **Active access**, **Access ended**, **Only me (test)**;
   - **By step**: customers who are currently on a chosen step of the funnel;
   - **By source**: customers who came from a chosen `?start=` link.
4. Check the count on the confirmation and press the green **Send** button (or red **Cancel**).

Details: messages go out at a safe pace, well under Telegram's limits. Customers who blocked the bot are skipped and marked. Customers who pressed `/stop` never receive broadcasts. If the server restarts mid-way, the broadcast resumes where it stopped. You get a summary when it finishes.

### Tracking where customers come from

Give each traffic source its own link: `https://t.me/your_bot?start=ads1`, `...?start=blogger_ivan`. The first link a customer used is remembered, shown in the stats and usable as a broadcast audience.

## Customer card

**Find user** (or **Customer** from an order) shows: name, @username, source, current step, consent, blocked or not, answers to your questions, all orders and all access. Buttons:

- **🎁 Give access**: pick a product; the customer receives it as if they had paid (message, files, channel link).
- **⛔ Take access**: pick a channel access; the customer is removed from the channel.
- **🗑 Erase data**: erases personal data and ends access after a confirmation. Order records stay for accounting.

## Refunds

**Payments** → tap the order → **Refund** → confirm. Stars go back automatically. For other methods you return the money in that service, and the order is marked refunded. Access given by the order ends.

## Alerts

The bot writes to your manager chat (or to you if there is none) when something needs attention: a payment that matches no order, a duplicate payment, a failed delivery that is being retried, the bot lacking rights in a channel, a payment service refusing a request. Each kind of alert is sent at most once an hour.

## Commands (optional)

Every panel action also exists as a command for people who prefer typing:

| Command | Meaning |
|---|---|
| `/admin` | Open the panel |
| `/stats`, `/leads`, `/payments` | Statistics, CSV, latest orders |
| `/user <id or @name>` | Customer card as text |
| `/grant <id or @name> <product>` / `/revoke <id or @name> <product>` | Give or take access |
| `/refund <order number>` | Refund |
| `/erase <id or @name>` | Erase personal data |
| `/broadcast <segment>` (as a reply) | Broadcast the message you reply to. Segments: `all`, `paid`, `unpaid`, `active`, `expired`, `test`, `step:<id>`, `source:<name>` |
| `/reload` | Reload the funnel |
| `/managerchat` | Make the current chat the manager chat (send it in a group where the bot is a member) |
| `/id` | Show your id and the id of the current chat (works for everyone) |

## Customer commands

`/help`, `/terms` (your documents), `/paysupport` (payment help with a button to contact you), `/deleteme` (erase my data), `/stop` and `/resume` (turn promotional messages off and on; notices about access still arrive). Telegram's rules require the payment help and data erasure, so they are always available.
