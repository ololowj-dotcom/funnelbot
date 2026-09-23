# Payments

funnelbot accepts five kinds of payment. You can switch on any of them and let a product be bought in several ways. This page explains how each works, how to get its keys and what Telegram's rules say.

> Русская версия: [ru/payments.md](ru/payments.md)

## Telegram's rules first

Telegram's Bot Developer Terms say that **digital goods and services must be paid for in Telegram Stars**. Access to a private channel, a PDF, a video course and an online consultation are digital. Physical goods and services delivered in the real world may use other providers.

What this means in practice:

- If you sell digital things, **turn on Stars** and give every such product a price in `XTR`.
- You may add other methods, but you do it at your own risk, and `funnelbot validate` prints a warning for every digital product that can be paid by a non-Stars method.
- The terms also require you to answer payment questions and handle refunds. funnelbot provides `/paysupport` for customers and a refund button in the admin panel.

The rules can change, so read the current terms at <https://telegram.org/tos/bot-developers>.

## How an order works

1. The customer opens a product card and chooses a method (if there is only one, the button simply says "Pay now").
2. The bot creates an **order** and shows the invoice or a payment link.
3. When the payment is confirmed the order becomes **paid** and funnelbot delivers everything in the product's `access` list, then moves the customer to the step named in `paid`.
4. If delivery fails halfway (for example Telegram is unavailable), the order stays paid and funnelbot retries every minute, without repeating what was already delivered. You are alerted.

Safety nets:

- Each order is processed exactly once, even if Telegram sends the same notification twice.
- A payment that arrives after its link expired is still honoured.
- If money arrives for an order the database does not know (for example after restoring an old backup), you get an alert with all the details so you can refund or grant access by hand.
- Prices are checked again at the last moment, before Telegram charges the customer.

## Telegram Stars

Works out of the box, no account or keys.

```yaml
payments:
  stars: true
products:
  club:
    title: Private club
    prices: {XTR: 500}
```

Prices are whole numbers of Stars. Refunds from the admin panel return the Stars to the customer automatically. Stars you earn accumulate on your bot's balance. For how to withdraw them, fees and holding periods, follow Telegram's current documentation.

## Bank cards through a Telegram payment provider

Telegram connects your bot to providers such as YooKassa, Stripe and others (availability depends on your country and the provider). The customer pays inside Telegram.

1. In Telegram open @BotFather, send `/mybots`, choose your bot, then **Payments**.
2. Choose a provider and follow its steps. BotFather gives you a **provider token**: a test one and, after the provider approves you, a live one.
3. Put it in `.env` (`PROVIDER_TOKEN=...`) and enable:

```yaml
payments:
  telegram:
    provider_token: ${PROVIDER_TOKEN}
    currency: RUB
    need_email: true        # ask for the email in the payment form
    receipt:                # only if you must send fiscal receipts
      vat_code: 1
      contact_key: email
products:
  course:
    prices: {RUB: 4900, XTR: 3000}
```

`funnelbot doctor` warns when the token is a test token. Use the provider's test cards to rehearse.

## YooKassa payment links

Direct integration with the YooKassa API. The bot creates a payment, gives the customer a link, and checks its status every few seconds. No webhook and no public address are needed.

1. In your YooKassa account create a shop and open **Integration → API keys**.
2. Note the **shop id** and issue a **secret key**. Put them in `.env`.
3. Enable:

```yaml
payments:
  yookassa:
    shop_id: ${YOOKASSA_SHOP_ID}
    secret_key: ${YOOKASSA_SECRET_KEY}
    return_url: https://t.me/your_bot     # where the customer returns after paying
    currency: RUB
    receipt: {vat_code: 1, contact_key: email}   # only if you send receipts through YooKassa
```

If you set `receipt`, the funnel must collect the customer's email or phone with an `ask` step whose `key` equals `contact_key`; `validate` checks this. YooKassa also has a test mode for shops: use it before going live. The customer sees an **"I have paid"** button that checks the payment immediately.

## Crypto Pay (@CryptoBot)

Accepts USDT, TON, BTC and other coins through Telegram's Crypto Pay service.

1. In Telegram open [@CryptoBot](https://t.me/CryptoBot), choose **Crypto Pay**, then **Create App**.
2. Copy the **API token** and put it in `.env`.
3. Enable, and give products a price in the coin you choose:

```yaml
payments:
  crypto:
    token: ${CRYPTO_PAY_TOKEN}
    asset: USDT
    expires_in: 1h
products:
  club:
    prices: {XTR: 500, USDT: 6}
```

To rehearse with test coins use [@CryptoTestnetBot](https://t.me/CryptoTestnetBot) and add `api_base: https://testnet-pay.crypt.bot/api`.

## Manual transfer with a screenshot

For bank transfers or anything else you confirm yourself.

```yaml
bot:
  manager_chat: ${MANAGER_CHAT}
payments:
  manual:
    text: "Transfer the amount to card 0000 0000 0000 0000, then send a screenshot here."
    currency: RUB
```

The customer sees your instructions with the amount and sends a screenshot. The bot forwards it to the manager chat with a **green Approve** and a **red Reject** button. One tap on Approve delivers the product and thanks the customer; Reject tells them politely that the payment could not be confirmed. Anyone in the manager chat can decide, so add only trusted people.

## Testing without real money

Set `bot: {test_mode: true}` and reload. Administrators then see an extra **Test payment** button on every product card. It completes an order instantly, delivers everything and records the order with the method `test`, which is left out of the statistics of real revenue. Turn it off before launch.

`funnelbot preview` rehearses the same on your computer without Telegram: type `:pay` after choosing a product.

## Refunds

Open `/admin` → **Payments**, tap the order, press **Refund** and confirm. Stars are returned automatically. For other methods funnelbot marks the order refunded and tells you to return the money in that service. In both cases the access given by that order is ended (the customer is removed from the channel).

## Which method should I offer?

| Situation | Suggestion |
|---|---|
| Digital access or files, any country | Stars |
| Russian customers who prefer cards | Stars **and** cards or YooKassa, aware of the rule above |
| Physical goods or a service in person | Cards or YooKassa |
| Customers who hold crypto | Crypto Pay in addition |
| Small audience, you check payments yourself | Manual transfer |
