import asyncio
import json

from fakeapi import FakeTelegram

from funnelbot.bot import run_bot

FUNNEL = """
bot:
  language: en
  admins: [1]
  manager_chat: -100500
payments:
  stars: true
products:
  club:
    title: Club
    description: Closed channel
    prices: {XTR: 500}
    access:
      - channel: {chat: -100123, days: 30}
start: welcome
steps:
  welcome:
    text: "Hi {first_name}"
    buttons:
      - [{text: Offer, goto: offer, style: primary, icon: "5368324170671202286"}]
      - [{text: Copy code, copy: PROMO}]
  offer:
    text: "Choose"
    paid: thanks
    buttons:
      - [{text: Club, pay: club}]
  thanks:
    text: "Thanks"
    end: true
"""


async def until(predicate, timeout=6.0):
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out waiting for the bot")


def markup(params):
    return json.loads(params["reply_markup"])["inline_keyboard"]


def test_full_purchase_through_aiogram(tmp_path):
    (tmp_path / "funnel.yaml").write_text(FUNNEL, encoding="utf-8")

    async def scenario():
        api = FakeTelegram()
        await api.start()
        task = asyncio.ensure_future(run_bot(tmp_path / "funnel.yaml", tmp_path / "bot.db", "123:ABC", api.url))
        try:
            await until(lambda: api.named("getMe"))
            api.message(5, "/start")
            await until(lambda: api.named("sendMessage"))
            first = api.named("sendMessage")[-1]
            assert first["text"] == "Hi User"
            keyboard = markup(first)
            assert keyboard[0][0]["style"] == "primary" and keyboard[0][0]["icon_custom_emoji_id"] == "5368324170671202286"
            assert keyboard[1][0]["copy_text"] == {"text": "PROMO"}

            api.press(5, "g:offer", 1001)
            await until(lambda: api.named("editMessageText"))
            api.press(5, "p:club", 1001)
            await until(lambda: len(api.named("editMessageText")) == 2)
            card = api.named("editMessageText")[-1]
            assert "Club" in card["text"] and markup(card)[0][0]["style"] == "success"

            api.press(5, "m:club:stars", 1001)
            await until(lambda: api.named("sendInvoice"))
            invoice = api.named("sendInvoice")[-1]
            assert invoice["currency"] == "XTR" and "provider_token" not in invoice
            assert json.loads(invoice["prices"]) == [{"label": "Club", "amount": 500}]
            pay = markup(invoice)[0][0]
            assert pay["pay"] is True and pay["style"] == "success"

            api.pre_checkout(5, invoice["payload"], "XTR", 500)
            await until(lambda: api.named("answerPreCheckoutQuery"))
            assert api.named("answerPreCheckoutQuery")[-1]["ok"] == "true"

            api.paid(5, invoice["payload"], "XTR", 500, "charge-1")
            await until(lambda: any("t.me/+FAKELINK" in p.get("text", "") for p in api.named("sendMessage")))
            assert api.named("createChatInviteLink")[-1]["creates_join_request"] == "true"
            await until(lambda: any(p.get("text") == "Thanks" for p in api.named("sendMessage")))

            api.join_request(-100123, 5)
            await until(lambda: api.named("approveChatJoinRequest"))
            api.join_request(-100123, 6)
            await until(lambda: api.named("declineChatJoinRequest"))
            assert api.named("approveChatJoinRequest")[-1]["user_id"] == "5"
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            await api.stop()

    asyncio.run(scenario())


def test_admin_stats_and_id_over_the_wire(tmp_path):
    (tmp_path / "funnel.yaml").write_text(FUNNEL, encoding="utf-8")

    async def scenario():
        api = FakeTelegram()
        await api.start()
        task = asyncio.ensure_future(run_bot(tmp_path / "funnel.yaml", tmp_path / "bot.db", "123:ABC", api.url))
        try:
            await until(lambda: api.named("getMe"))
            api.message(1, "/id")
            await until(lambda: any("Your id: 1" in p.get("text", "") for p in api.named("sendMessage")))
            api.message(1, "/stats")
            await until(lambda: any("Users:" in p.get("text", "") for p in api.named("sendMessage")))
            api.message(7, "/stats")
            await asyncio.sleep(0.3)
            assert not any(p.get("chat_id") == "7" for p in api.named("sendMessage"))
            assert api.named("setMyCommands")
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            await api.stop()

    asyncio.run(scenario())


def test_channel_id_helper(tmp_path):
    (tmp_path / "funnel.yaml").write_text(FUNNEL, encoding="utf-8")

    async def scenario():
        api = FakeTelegram()
        await api.start()
        task = asyncio.ensure_future(run_bot(tmp_path / "funnel.yaml", tmp_path / "bot.db", "123:ABC", api.url))
        try:
            await until(lambda: api.named("getMe"))
            api.push({"channel_post": {"message_id": 5, "date": 1, "chat": {"id": -100777, "type": "channel", "title": "C"},
                                       "text": "/id"}})
            await until(lambda: any("-100777" in p.get("text", "") for p in api.named("sendMessage")))
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            await api.stop()

    asyncio.run(scenario())


def test_builder_over_the_wire_with_photo_and_document(tmp_path):
    (tmp_path / "funnel.yaml").write_text(FUNNEL, encoding="utf-8")

    async def scenario():
        api = FakeTelegram()
        await api.start()
        task = asyncio.ensure_future(run_bot(tmp_path / "funnel.yaml", tmp_path / "bot.db", "123:ABC", api.url))
        try:
            await until(lambda: api.named("getMe"))
            api.message(1, "/admin")
            await until(lambda: any("Control panel" in p.get("text", "") for p in api.named("sendMessage")))
            menu = [b for p in api.named("sendMessage") for row in markup(p) for b in row if b["text"].startswith("🛠")]
            assert menu and menu[0]["callback_data"] == "ad:w"

            api.press(1, "ad:wn", 2001)
            await until(lambda: any("Send me the text" in p.get("text", "") for p in api.named("editMessageText")))
            api.message(1, "A brand new step")
            await until(lambda: "A brand new step" in (tmp_path / "funnel.yaml").read_text(encoding="utf-8"))

            api.press(1, "ad:wi:step_1", 2001)
            await until(lambda: any("photo" in p.get("text", "").lower() for p in api.named("editMessageText")))
            api.message(1, "", photo=[{"file_id": "SMALL", "file_unique_id": "a", "width": 1, "height": 1},
                                     {"file_id": "BIG", "file_unique_id": "b", "width": 9, "height": 9}])
            await until(lambda: "file_id:BIG" in (tmp_path / "funnel.yaml").read_text(encoding="utf-8"))
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            await api.stop()

    asyncio.run(scenario())
