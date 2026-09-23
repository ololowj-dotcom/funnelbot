# Building a funnel inside Telegram

You do not have to edit any file. The bot has a **funnel builder** in its admin panel: you create steps, buttons, products, reminders and private-channel access by pressing buttons and sending short messages. Every change is saved to `funnel.yaml` and applies immediately, with no restart.

> Русская версия: [ru/funnel-builder.md](ru/funnel-builder.md)

Open it: send `/admin` to your bot, then press **🛠 Build the funnel**.

## The idea in one minute

A funnel is a small map of messages:

- a **step** is one message the customer sees, with optional buttons under it;
- a **button** leads to another step, sells a product, opens a link or calls a manager;
- a **product** is what the customer buys and what they receive after paying: a private channel for some days, a message with a file, or a request to a manager;
- the **start step** is what a customer sees first.

You build it from the outside in: first create the product, then the steps, then join them with buttons.

## Example: a paid private channel in 5 minutes

Assume the channel already exists and the bot is its administrator (see [Private channel access](private-channel-access.md), steps 1 to 3).

1. **Create the product.** Builder → **🛍 Products** → **➕ New product**. Send the name ("Members club"), press **Skip** for the description (or send one), then send the price in Stars, for example `500`.
2. **Say what the customer gets.** On the product screen press **➕ What they get** → **📢 Access to a private channel**. Send the channel id (post `/id` in the channel to see it) and choose the duration: 7, 30, 90, 365 days or forever. Reminders 3 and 1 days before the end are added for you.
3. **Write the offer.** Builder → **📋 Steps** → open the first step (the start step) → **✏️ Text** and send the greeting, for example "Hi! Join the club for 500 ⭐".
4. **Add the buy button.** On the step press **➕ Button** → **💳 Buy a product** → choose "Members club" → send the button text ("Join") → choose a colour (green works well).
5. **Try it.** Builder → **▶️ See it as a customer**. Press the button, pay with the free test payment (turn on test mode in **💳 Payments and language**), and check `/admin` → **🩺 Health check**.

That is the whole funnel. Everything else below makes it richer.

## Steps

**📋 Steps** lists every step; the start step has a star. Tap a step to open its screen, which shows its text, picture, buttons, reminders and question, with these actions:

| Button | What it does |
|---|---|
| ✏️ Text | Replace the message text. You can use bold text, and `{first_name}` for the customer's name |
| 🖼 Picture | Send a photo (as a photo, not a file) to show above the text. You can remove it later |
| ➕ Button | Add a button (below) |
| 🗑 Button | Delete a button |
| ⏰ Reminders | Send a message later if the customer does nothing |
| ❓ Ask a question | Ask for a name, email, phone or number |
| ⭐ Make it the start | This step becomes the first one customers see |
| 🗑 Delete step | Remove the step and every button that led to it (the start step cannot be deleted) |

### Buttons

Press **➕ Button** and choose what it does:

- **➡️ Go to a step**: pick an existing step, or **➕ New step** to write a new one on the spot;
- **💳 Buy a product**: pick one of your products;
- **🔗 Open a link**: send a link starting with `https://`;
- **👨‍💼 Call the manager**: notifies your manager chat (shown only when a manager chat is set);
- **↩️ Back** and **🏠 To the start**: added at once with a ready label.

Then send the text for the button and pick its colour: 🔵 blue, 🟢 green, 🔴 red or ⚪ plain. Buttons are added one per row.

### Reminders

**⏰ Reminders** sends a message after 1 hour, 3 hours, 1 day or 3 days if the customer is still on the step. The reminder repeats the step's buttons, so add your buttons first. A customer who already bought, pressed `/stop`, or has an open payment is skipped. Tap an existing reminder to delete it.

### Questions

**❓ Ask a question** turns a step into a question: the customer types an answer, it is checked (a real email or phone), saved with their card, exported to CSV and usable in later texts as `{email}`, `{phone}`, `{name}` or `{number}`. You then choose which step follows. A question step cannot have buttons. Press **Remove the question** to make it an ordinary step again.

## Products

**🛍 Products** lists your products. A product screen shows its name, description, prices and what it gives, with these actions:

| Button | What it does |
|---|---|
| ✏️ Name, ✏️ Description | Change the text shown on the product card |
| 💰 Prices | Set the price in each payment currency that is switched on |
| ➕ What they get | Add a gift, see below |
| 🗑 Remove a gift | Remove one of the gifts |
| 🗑 Delete product | Delete it together with every buy button that used it |

**What they get** can be:

- **📢 Access to a private channel**: send the channel id, choose the duration. If the bot cannot invite or remove people there, you get a warning immediately;
- **📄 A message and a file**: send the message text and then a file **as a document** (or press **No file**). The file is stored by Telegram, so nothing is uploaded to your server;
- **👨‍💼 A request to the manager**: sends an order card to the manager chat and your message to the customer.

A product may give several things at once, for example a channel and a PDF.

## Payments and language

**💳 Payments and language** shows which payment methods are on, the manager chat, test mode and the language.

- **Telegram Stars** can be switched on and off here. Stars work without any keys.
- **Test mode** gives administrators a free "Test payment" button on product cards. Switch it off before you launch.
- **Language** switches every message of the bot between Russian and English.
- **Manager chat**: add the bot to a group and send `/managerchat` there. Order cards, "call a manager" requests and manual-payment screenshots then arrive in that group.
- **Cards, YooKassa, Crypto Pay and manual transfer** need secret keys, which should never be typed into a chat. Put them into `.env` and `funnel.yaml` as described in [Payments](payments.md); the builder then shows the currency of each method and offers prices in it.

## How your changes are saved

- Every action rewrites `funnel.yaml`, checks it, and only then applies it. If a change would make the funnel invalid, nothing is changed and you see the reason.
- The previous version is kept as `funnel.yaml.bak`.
- The file is rewritten in a standard layout, so **comments you typed into `funnel.yaml` by hand are not preserved** once you use the builder. `${NAME}` placeholders for secrets are kept.
- You can mix both ways. The builder reads the file before each change, so edits made by hand are picked up (press **Reload funnel** in `/admin` after editing by hand, so the running bot uses them).

## What the builder does not cover

Use `funnel.yaml` ([Configuration](configuration.md)) for: several buttons in one row, the consent screen, question types "choice" and "regex", step-level payment blocks, custom emoji on buttons, bank-card, YooKassa, crypto and manual-transfer settings, and overriding built-in phrases. Files of the funnel stay valid either way, and `funnelbot validate` checks them.
