# Private channel access

The most popular use of funnelbot: customers pay, and the bot lets them into a **private channel or group** for a chosen number of days, warns them before the end and removes them when time is up.

> Русская версия: [ru/private-channel-access.md](ru/private-channel-access.md)

## Connect a channel in 4 steps

**1. Make the channel (or group) private.** In Telegram create a channel, open its settings, and set the type to **Private**. Do not share its invite link anywhere: funnelbot creates its own.

**2. Add the bot as an administrator.** Channel settings → **Administrators** → **Add administrator** → find your bot. Give it exactly these rights and no more:

- **Invite users via link** (needed to create the join link and approve requests);
- **Ban users** (needed to remove people when their access ends).

**3. Get the channel id.** Post a message `/id` in the channel. The bot answers with a line like `This chat id: -1001234567890`. Copy the number, then delete both messages. (For a group, send `/id` in the group.)

**4. Put it into a product.** The easiest way is in the bot: `/admin` → **🛠 Build the funnel** → **🛍 Products** → open (or create) the product → **➕ What they get** → **📢 Access to a private channel**, then send the id and choose the duration. If you prefer the file, use this:

```yaml
products:
  club:
    title: Private club
    prices: {XTR: 500}
    access:
      - channel: {chat: -1001234567890, days: 30, remind_days: [3, 1]}
```

Reload the funnel and open `/admin` → **Health check**. It says whether the bot can invite and remove people in that channel. `funnelbot doctor` runs the same check from the server.

## What the customer sees

1. They pay. The bot sends: "Your access to Private club is active until 14.02.2027. Request to join here: ...".
2. They open the link and press **Request to join**.
3. The bot **approves the request instantly** and says "Welcome!". Anyone who is not a paying customer is declined automatically.

The join link is created once and reused. It is a "request to join" link, so it cannot let in an unpaid person even if it leaks: nobody enters without the bot's approval. That is why funnelbot never uses an ordinary invite link.

## Reminders, expiry and renewal

- `days: 30` starts counting at the moment of payment.
- `remind_days: [3, 1]` sends "Your access ends in 3 days" and "...in 1 day", each with a **Renew access** button. If the bot was offline and both are due, only the most urgent one is sent.
- When the time is up the customer is removed from the channel (they are not banned and can come back after renewing) and gets "Your access has ended" with a **Renew access** button.
- If Telegram refuses to remove someone (for example the bot lost its rights), funnelbot **keeps retrying** with growing pauses and alerts you after a few failures. Nothing is marked finished until the removal succeeded.
- Buying again while access is active **extends** it from the current end date, and the reminders start over. The customer does not need a new link if they are already inside.
- No `days` means lifetime access.

Set `bot.enforce_expiry: false` if you want funnelbot to track dates but never remove anybody.

## Several channels, several products

A product can list several `channel` items (for example a channel and a chat), and several products can share one channel. If a customer has two products giving the same channel, they are removed only when both have ended.

## Give or take access by hand

Open `/admin` → **Find user**, send their id or @username, then **Give access** (choose the product) or **Take access**. Giving access works exactly like a paid order, without money, and shows as a `grant` in the order history (it is excluded from revenue statistics).

## Troubleshooting

| Problem | Likely cause and fix |
|---|---|
| `/id` in the channel gets no answer | The bot is not an administrator of the channel yet, or you wrote it in a different channel |
| Health check: "the bot is not an administrator" | Add the bot as administrator (step 2) |
| Health check: "lacks rights: can_restrict_members" | Give the bot the right **Ban users** |
| Health check: "lacks rights: can_invite_users" | Give the bot the right **Invite users via link** |
| A paying customer says the link does not work | They must press **Request to join**, and the request comes from the same account that paid. `/admin` → Find user shows their access |
| Someone was not removed on time | The bot cannot remove administrators and the channel owner. Check the alert in your admin chat |
