# Configuration reference

Everything about your funnel lives in one YAML file, `funnel.yaml`. You can build most of it without touching the file, with the [funnel builder in the admin panel](funnel-builder.md); this page is for editing by hand and for the options the builder does not cover. Once the builder changes the file it rewrites it in a standard layout, so hand-written comments are not kept. This page lists every setting. Run `funnelbot validate` after any change: it reports **all** mistakes at once, with hints such as "did you mean 'buttons'?".

> Русская версия: [ru/configuration.md](ru/configuration.md)

## File layout

```yaml
bot:        # who manages the bot, language, defaults
consent:    # optional: "I agree" screen before the funnel starts
payments:   # which payment methods are on and their keys
products:   # what you sell and what the customer gets
start: welcome   # the first step
steps:      # the conversation
```

## Secrets and the .env file

Never write tokens into `funnel.yaml`. Put them in the `.env` file next to it and refer to them:

```yaml
payments:
  yookassa:
    shop_id: ${YOOKASSA_SHOP_ID}
    secret_key: ${YOOKASSA_SECRET_KEY}
```

- `${NAME}` is replaced by the value of `NAME` from `.env` or from the environment. A missing value is an error.
- `${NAME:-default}` uses `default` when `NAME` is empty.
- Placeholders work in every text value of the file.

## Durations

`30s`, `10m`, `2h`, `1d`. A bare number means minutes.

## Text placeholders

Inside step texts, nudges and delivered messages you can use:

| Placeholder | Meaning |
|---|---|
| `{first_name}` | The customer's first name |
| `{username}` | Their @username without the @ |
| `{id}` | Their Telegram id |
| `{email}`, `{phone}`, any `ask.key` | An answer the customer gave earlier |
| `{product}` | The product title, in `access.message.text` only |

Values are escaped automatically, so a customer cannot inject formatting. Text is HTML by default: `<b>bold</b>`, `<i>italic</i>`, `<a href="...">link</a>`, `<code>code</code>`. To send plain text set `bot.parse_mode: none`.

To show a literal `{` or `}` write `{{` or `}}`.

## bot

```yaml
bot:
  language: ru            # ru (default) or en: language of every built-in message
  admins: ["${ADMIN_ID}"] # Telegram user ids that may use /admin. Optional: you can claim the bot with a link instead
  manager_chat: ${MANAGER_CHAT:-}  # chat id that receives order cards and payment screenshots
  parse_mode: html        # html (default) or none
  enforce_expiry: true    # false: never remove people from channels, only track the end date
  test_mode: false        # true: admins get a free "Test payment" button
  pay_style: success      # colour of pay buttons: primary (blue), success (green), danger (red) or none
  texts:                  # override any built-in phrase, see below
    paid_thanks: "Thank you, the payment went through!"
```

- **admins**: get the id by sending `/id` to the bot. Or leave the list empty and use the claim link printed by `funnelbot setup` or `funnelbot link`.
- **manager_chat**: create a group, add the bot and yourself, send `/id` in it, and copy the number (it usually starts with `-100` or `-`). Required if you use `manager` buttons, `manager` access or the `manual` payment method.
- **texts**: keys of the built-in phrases (see `src/funnelbot/texts.py` for the full list): `back`, `home`, `agree`, `use_buttons`, `pay_now`, `pay_stars`, `pay_telegram`, `pay_yookassa`, `pay_crypto`, `pay_manual`, `pay_check`, `pay_waiting`, `pay_failed`, `pay_expired`, `paid_thanks`, `access_channel`, `access_until`, `access_renewed`, `access_reminder`, `access_expired`, `renew`, `join_approved`, `join_declined`, `manager_called`, `help`, `terms`, `paysupport`, `deleted`, `stopped`, `resumed` and more. An unknown key is an error with a suggestion.

## consent

Shows a consent screen before anything else. Customers must press the button to continue. Recommended if you collect personal data (for example under GDPR or Russian 152-FZ).

```yaml
consent:
  text: "Please confirm you agree to the terms."
  agree: "I agree"          # optional, defaults to the built-in phrase
  documents:
    - {title: Terms of service, url: "https://example.com/terms"}
    - {title: Privacy policy, url: "https://example.com/privacy"}
```

The same documents are shown by `/terms`.

## payments

Turn on the methods you need. Details and how to get the keys: [Payments](payments.md).

```yaml
payments:
  stars: true
  telegram:
    provider_token: ${PROVIDER_TOKEN}
    currency: RUB
    need_email: false
    receipt: {vat_code: 1, tax_system_code: 1, payment_subject: service, payment_mode: full_payment, contact_key: email}
  yookassa:
    shop_id: ${YOOKASSA_SHOP_ID}
    secret_key: ${YOOKASSA_SECRET_KEY}
    return_url: https://t.me/your_bot
    currency: RUB
    receipt: {vat_code: 1, contact_key: email}
  crypto:
    token: ${CRYPTO_PAY_TOKEN}
    asset: USDT
    expires_in: 1h
  manual:
    text: "Transfer the amount to card 0000 0000 0000 0000 and send a screenshot."
    currency: RUB
  poll_seconds: 20     # how often YooKassa and Crypto Pay orders are checked
  pending_ttl: 1d      # after this time an unpaid order expires
```

Each method has one currency: Stars are always `XTR`, the others use the `currency`/`asset` you set. A product can be bought by a method only if it has a price in that method's currency.

`receipt` is for fiscal receipts (for example Russian 54-FZ). `contact_key` names the answer that holds the customer's email or phone, collected with an `ask` step.

## products

```yaml
products:
  club:                              # the id: lowercase letters, digits, underscore
    title: Private club
    description: Closed channel with weekly materials.
    image: files/club.jpg            # optional picture on the product card
    prices: {XTR: 500, RUB: 4900, USDT: 55}
    access:
      - channel: {chat: -1001234567890, days: 30, remind_days: [3, 1]}
      - message: {text: "Welcome, {first_name}!", files: [files/guide.pdf, files/bonus.zip]}
      - manager: {text: "Thanks! We will write to you soon."}
```

### access items

An `access` list says what happens after a **successful payment**. You can combine several items.

| Item | Keys | What it does |
|---|---|---|
| `channel` | `chat` (required), `days`, `remind_days` | Gives a join link for a private channel or group. With `days` the access ends after that time. `remind_days` (a number or a list, each smaller than `days`) sends renewal reminders that many days before the end. Without `days` the access never ends |
| `message` | `text`, `file`, `files` | Sends a message and/or files right away. Files are uploaded once and reused |
| `manager` | `text` | Sends a card to `manager_chat` and a text to the customer |

Buying the same channel product again extends the access from the current end date.

Paths for images and files are relative to the folder of `funnel.yaml`. You can also use an `https://` link or `file_id:<Telegram file id>`.

## steps

```yaml
steps:
  welcome:
    text: "Hi, <b>{first_name}</b>!"
    image: files/hello.jpg
    buttons:
      - [{text: Details, goto: about, style: primary}]
      - [{text: Buy, pay: club}, {text: Ask, manager: true}]
    nudges:
      - after: 3h
        text: "Still thinking?"
        buttons:
          - [{text: Show the offer, goto: offer}]
```

| Key | Meaning |
|---|---|
| `text` | Message text (required) |
| `image` | Picture sent with the text |
| `buttons` | Rows of buttons. Each inner list is one row (up to 8 buttons) |
| `next` | Step to go to automatically |
| `wait` | With `next`: wait this long before moving on |
| `ask` | Ask the customer a question and wait for the answer, then go to `next` |
| `pay` | Show the payment method buttons for this product under the text |
| `paid` | Step to show after a purchase made in this step |
| `nudges` | Reminders sent if the customer does nothing |
| `end` | `true` marks a final step (no warning about dead ends) |

A step with `next` and nothing else moves on immediately, which lets you chain several messages.

### buttons

Every button has `text` and exactly one action:

| Action | Value | Result |
|---|---|---|
| `goto` | step id | Go to another step |
| `pay` | product id | Open the product card with payment methods |
| `url` | link | Open a link |
| `copy` | text (up to 256 chars) | Copy the text to the clipboard (promo code, address) |
| `back` | `true` | Go to the previous step |
| `home` | `true` | Go to the start step |
| `manager` | `true` | Notify the manager chat and tell the customer someone will write |

Extra keys: `style` (`primary` blue, `success` green, `danger` red) and `icon` (the id of a custom emoji, a long number). Colours and custom emoji need a recent Telegram app.

### ask

```yaml
  ask_email:
    text: "What is your email?"
    ask: {key: email, type: email, error: "That does not look like an email."}
    next: offer
```

`type` is `text`, `email`, `phone`, `number`, `choice` (with `choices: [S, M, L]`, shown as buttons) or `regex` (with `regex: '\d{6}'`). The answer is saved under `key`, shown in `/admin` → customer card, exported by `funnelbot export`, and usable as `{key}` in later texts. A short form `ask: name` asks for free text saved as `name`.

### nudges

Reminders for customers who stopped at a step. `after` counts from the moment the customer reached the step. Each nudge is sent once and only if the customer is still there. It is skipped when the customer already bought the product in its buttons, opened a payment in the last hour, blocked the bot or pressed `/stop`. If the bot was offline and several nudges are due, only the latest is sent.

## Validation you get for free

`funnelbot validate` and the panel's Reload check, among other things: unknown keys and steps, buttons without an action, texts with unknown `{placeholders}`, missing files, prices without a matching payment method, receipts without a contact, manager features without `manager_chat`, unreachable and dead-end steps, and digital products sold by methods other than Stars (a warning that cites Telegram's rules).
