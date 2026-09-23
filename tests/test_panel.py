import asyncio

from conftest import incoming


async def buy_club(w, uid=5, charge="ch"):
    await w.start(uid, username=f"u{uid}")
    await w.press(uid, "Offer")
    await w.press(uid, "Club")
    await w.press(uid, "Pay now")
    await w.pay_stars(uid, charge=charge)


async def open_panel(w, admin=1):
    await w.command(admin, "admin")
    return w.transport.last(admin)


def test_menu_is_all_buttons(world):
    w = world()

    async def scenario():
        menu = await open_panel(w)
        labels = [b.text for row in menu.keyboard for b in row]
        assert labels == ["📊 Stats", "👥 Leads (CSV)", "🛠 Build the funnel", "📣 Broadcast", "💳 Payments",
                          "🔎 Find user", "🩺 Health check", "🔄 Reload funnel"]
        assert menu.keyboard[2][0].style == "primary"

    w.run(scenario())


def test_panel_is_admin_only(world):
    w = world()

    async def scenario():
        await w.start(5)
        count = len(w.transport.to(5))
        await w.command(5, "admin")
        await w.engine.on_callback(incoming(5, data="ad:s", callback_id="x", message_id=1))
        assert len(w.transport.to(5)) == count

    w.run(scenario())


def test_stats_screen_edits_in_place(world):
    w = world()

    async def scenario():
        await buy_club(w, 5)
        await open_panel(w)
        await w.press(1, "Stats")
        message = w.transport.last(1)
        assert message.edited and "Buyers: 1" in message.text
        await w.press(1, "Panel")
        assert w.transport.last(1).text.startswith("Control panel")

    w.run(scenario())


def test_claim_first_admin_with_code(world):
    def mutate(raw):
        raw["bot"]["admins"] = []

    w = world(mutate)
    w.engine.claim_code = "secret1"

    async def scenario():
        await w.command(9, "claim", "wrong")
        assert "Nothing to claim" in w.transport.last(9).text
        await w.start(9, payload="claim_secret1")
        assert "now the administrator" in w.transport.last(9).text
        assert w.engine.is_admin(9)
        await w.press(9, "control panel")
        assert w.transport.last(9).text.startswith("Control panel")
        await w.command(10, "claim", "secret1")
        assert not w.engine.is_admin(10)

    w.run(scenario())


def test_claim_disabled_when_config_has_admin(world):
    w = world()
    w.engine.claim_code = "secret1"

    async def scenario():
        await w.command(9, "claim", "secret1")
        assert not w.engine.is_admin(9)

    w.run(scenario())


def test_find_user_and_give_access_by_buttons(world):
    w = world()

    async def scenario():
        await w.start(5, username="bob")
        await open_panel(w)
        await w.press(1, "Find user")
        await w.say(1, "@bob")
        card = w.transport.last(1)
        assert "id 5 @bob" in card.text
        await w.press(1, "Give access")
        assert [b.text for b in w.transport.buttons(1)][:2] == ["Private club".replace("Private club", "Club"), "Guide"]
        await w.press(1, "Club")
        assert w.store.user_grants(5)[0]["status"] == "active"
        assert "Done" in w.transport.last(1).text
        await w.press(1, "Customer")
        await w.press(1, "Take access")
        await w.press(1, "club (until")
        assert w.transport.removed == [(-100123, 5)]
        assert "removed from the channel" in w.transport.last(1).text

    w.run(scenario())


def test_find_unknown_user(world):
    w = world()

    async def scenario():
        await open_panel(w)
        await w.press(1, "Find user")
        await w.say(1, "999")
        assert "No such user" in w.transport.last(1).text

    w.run(scenario())


def test_refund_through_buttons_with_confirmation(world):
    w = world()

    async def scenario():
        await buy_club(w, 5, charge="chargeZ")
        await open_panel(w)
        await w.press(1, "Payments")
        await w.press(1, "#1 club")
        await w.press(1, "Refund")
        assert "Refund order #1?" in w.transport.last(1).text
        assert w.transport.refunds == []
        await w.press(1, "Yes, refund")
        assert w.transport.refunds == [(5, "chargeZ")]
        assert w.store.user_payments(5)[0]["status"] == "refunded"

    w.run(scenario())


def test_erase_through_buttons(world):
    w = world()

    async def scenario():
        await buy_club(w, 5)
        await open_panel(w)
        await w.press(1, data="ad:u:5")
        await w.press(1, "Erase data")
        await w.press(1, "Yes, erase")
        assert w.store.user(5)["erased"] == 1
        assert w.transport.removed == [(-100123, 5)]

    w.run(scenario())


def test_broadcast_by_buttons(world):
    w = world()

    async def scenario():
        await buy_club(w, 5)
        await w.start(6)
        await open_panel(w)
        await w.press(1, "Broadcast")
        assert "Send me the message" in w.transport.last(1).text
        await w.say(1, "Big news", message_id=321)
        chooser = w.transport.last(1)
        labels = [b.text for row in chooser.keyboard for b in row]
        assert "Everyone (3)" in labels and "Buyers (1)" in labels and "Only me (test) (1)" in labels
        await w.press(1, "Buyers")
        assert "copied to 1 users" in w.transport.last(1).text
        await w.press(1, "Send to 1")
        await asyncio.gather(*w.engine.tasks)
        assert w.transport.copies == [(5, 1, 321)]

    w.run(scenario())


def test_broadcast_with_photo_and_step_segment(world):
    w = world()

    async def scenario():
        await w.start(5)
        await w.start(6)
        await w.press(6, "Offer")
        await open_panel(w)
        await w.press(1, "Broadcast")
        await w.engine.on_photo(incoming(1, message_id=55, photo="p"))
        await w.press(1, "By step")
        assert {b.text for b in w.transport.buttons(1)} >= {"welcome (1)", "offer (1)"}
        await w.press(1, "offer (1)")
        await w.press(1, "Send to 1")
        await asyncio.gather(*w.engine.tasks)
        assert w.transport.copies == [(6, 1, 55)]

    w.run(scenario())


def test_broadcast_draft_lost(world):
    w = world()

    async def scenario():
        await open_panel(w)
        await w.press(1, data="ad:bs:all")
        assert "draft is gone" in w.transport.last(1).text

    w.run(scenario())


def test_health_report(world):
    w = world()
    w.transport.chat_problems[-100123] = "the bot is not an administrator of 'Club'"

    async def scenario():
        await open_panel(w)
        await w.press(1, "Health check")
        text = w.transport.last(1).text
        assert "❌ channel -100123: the bot is not an administrator" in text
        assert "✅ manager chat -100500 is set" in text
        assert "paid orders waiting for delivery: 0" in text

    w.run(scenario())


def test_leads_button_sends_csv(world):
    w = world()

    async def scenario():
        await w.start(5)
        await open_panel(w)
        await w.press(1, "Leads")
        assert w.transport.documents[-1][1] == "leads.csv"

    w.run(scenario())


def test_cancel_wait_when_pressing_menu(world):
    w = world()

    async def scenario():
        await open_panel(w)
        await w.press(1, "Find user")
        await w.press(1, "Cancel")
        await w.say(1, "5")
        assert w.transport.last(1).text == "Please use the buttons."

    w.run(scenario())
