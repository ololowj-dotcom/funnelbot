import asyncio

from conftest import incoming

DAY = 86400


async def buy_club(w, uid=5, charge="ch"):
    await w.start(uid, username=f"u{uid}")
    await w.press(uid, "Offer")
    await w.press(uid, "Club")
    await w.press(uid, "Pay now")
    await w.pay_stars(uid, charge=charge)


def test_non_admin_commands_ignored(world):
    w = world()

    async def scenario():
        await w.start(5)
        count = len(w.transport.to(5))
        await w.command(5, "stats")
        await w.command(5, "grant", "5", "club")
        assert len(w.transport.to(5)) == count

    w.run(scenario())


def test_id_command_for_everyone(world):
    w = world()

    async def scenario():
        await w.command(42, "id")
        assert "Your id: 42" in w.transport.last(42).text

    w.run(scenario())


def test_stats_and_leads(world):
    w = world()

    async def scenario():
        await buy_club(w, 5)
        await w.start(6, payload="ads")
        await w.command(1, "stats")
        text = w.transport.last(1).text
        assert "Users: 2" in text and "Buyers: 1" in text and "Revenue XTR" in text and "ads 1" in text
        await w.command(1, "leads")
        chat, name, content = w.transport.documents[-1]
        assert name == "leads.csv" and b"u5" in content and content.startswith(b"\xef\xbb\xbf")

    w.run(scenario())


def test_grant_and_revoke(world):
    w = world()

    async def scenario():
        await w.start(5, username="bob")
        await w.command(1, "grant", "@bob", "club")
        assert w.store.user_grants(5)[0]["status"] == "active"
        assert any("t.me/+link" in t for t in w.transport.texts(5))
        await w.command(1, "revoke", "5", "club")
        assert w.transport.removed == [(-100123, 5)]
        assert w.store.user_grants(5)[0]["status"] == "ended"
        await w.command(1, "grant", "999", "club")
        assert "has not opened the bot" in w.transport.last(1).text
        await w.command(1, "grant", "5", "nope")
        assert "Unknown product" in w.transport.last(1).text

    w.run(scenario())


def test_revenue_ignores_grants(world):
    w = world()

    async def scenario():
        await w.start(5)
        await w.command(1, "grant", "5", "club")
        await w.command(1, "stats")
        assert "Revenue" not in w.transport.last(1).text
        assert "Buyers: 0" in w.transport.last(1).text

    w.run(scenario())


def test_refund_stars_ends_access(world):
    w = world()

    async def scenario():
        await buy_club(w, 5, charge="chargeX")
        await w.command(1, "refund", "1")
        assert w.transport.refunds == [(5, "chargeX")]
        assert w.store.user_payments(5)[0]["status"] == "refunded"
        assert w.transport.removed == [(-100123, 5)]
        await w.command(1, "refund", "1")
        assert "nothing to refund" in w.transport.last(1).text

    w.run(scenario())


def test_refund_other_method_warns(world):
    def mutate(raw):
        raw["payments"]["manual"] = {"text": "x", "currency": "RUB"}
        raw["products"]["club"]["prices"] = {"XTR": 500, "RUB": 100}

    w = world(mutate)

    async def scenario():
        await w.start(5)
        pid = w.store.add_payment(5, "club", "manual", "100", "RUB", "paid", w.clock.t)
        await w.command(1, "refund", str(pid))
        assert "NOT returned automatically" in w.transport.last(1).text
        assert w.transport.refunds == []

    w.run(scenario())


def test_user_card(world):
    w = world()

    async def scenario():
        await buy_club(w, 5)
        await w.command(1, "user", "5")
        text = w.transport.last(1).text
        assert "id 5 @u5" in text and "payment #1 club 500 XTR stars paid" in text and "access club" in text

    w.run(scenario())


def test_deleteme_flow(world):
    w = world()

    async def scenario():
        await buy_club(w, 5)
        await w.command(5, "deleteme")
        assert [b.text for b in w.transport.buttons(5)] == ["Yes, erase", "Cancel"]
        await w.press(5, "Cancel")
        assert w.store.user(5)["erased"] == 0
        await w.command(5, "deleteme")
        await w.press(5, "Yes, erase")
        user = w.store.user(5)
        assert user["erased"] == 1 and user["username"] == "" and user["answers"] == {}
        assert w.transport.removed == [(-100123, 5)]
        assert w.store.user_payments(5)

    w.run(scenario())


def test_erase_by_admin(world):
    w = world()

    async def scenario():
        await w.start(5, first_name="Zed")
        await w.command(1, "erase", "5")
        assert w.store.user(5)["first_name"] == ""

    w.run(scenario())


def test_stop_and_resume_affect_nudges_only(world):
    def mutate(raw):
        raw["steps"]["welcome"]["nudges"] = [{"after": "1h", "text": "Ping"}]

    w = world(mutate)

    async def scenario():
        await w.start(5)
        await w.start(6)
        await w.command(6, "stop")
        await w.tick(3700)
        assert "Ping" in w.transport.texts(5)
        assert "Ping" not in w.transport.texts(6)
        await w.command(6, "resume")
        assert w.store.user(6)["stopped"] == 0

    w.run(scenario())


def test_terms_and_paysupport(world):
    def mutate(raw):
        raw["consent"] = {"text": "ok", "documents": [{"title": "Offer", "url": "https://x.io/o"}]}

    w = world(mutate)

    async def scenario():
        await w.command(5, "terms")
        assert w.transport.buttons(5)[0].url == "https://x.io/o"
        await w.command(5, "paysupport")
        assert "payment questions" in w.transport.last(5).text
        assert w.transport.buttons(5)[0].data == "mg"

    w.run(scenario())


def test_broadcast_segments_and_confirmation(world):
    w = world()

    async def scenario():
        await buy_club(w, 5)
        await w.start(6)
        await w.start(7)
        await w.command(7, "stop")
        await w.command(1, "broadcast", "paid", reply_to=900, reply_chat=1)
        prompt = w.transport.last(1)
        assert "1 users" in prompt.text
        assert [b.style for b in prompt.keyboard[0]] == ["success", "danger"]
        await w.press(1, data=prompt.keyboard[0][0].data)
        for _ in range(20):
            await asyncio.sleep(0.01)
            if not w.engine.tasks:
                break
        assert w.transport.copies == [(5, 1, 900)]
        assert "Broadcast finished: delivered 1" in w.transport.last(1).text
        assert w.store.broadcast(1)["status"] == "done"

    w.run(scenario())


def test_broadcast_all_skips_stopped_and_marks_blocked(world):
    w = world()

    async def scenario():
        for uid in (5, 6, 7):
            await w.start(uid)
        await w.command(7, "stop")
        w.transport.blocked.add(6)
        await w.command(1, "broadcast", "all", reply_to=900, reply_chat=1)
        await w.press(1, data=w.transport.last(1).keyboard[0][0].data)
        await asyncio.gather(*w.engine.tasks)
        assert w.transport.copies == [(5, 1, 900)]
        assert w.store.user(6)["blocked"] == 1
        assert "delivered 1, failed 1" in w.transport.last(1).text

    w.run(scenario())


def test_broadcast_cancel_and_errors(world):
    w = world()

    async def scenario():
        await w.start(5)
        await w.command(1, "broadcast", "all")
        assert "Easier way" in w.transport.last(1).text
        await w.command(1, "broadcast", "bogus", reply_to=1, reply_chat=1)
        assert "Unknown segment" in w.transport.last(1).text
        await w.command(1, "broadcast", "paid", reply_to=1, reply_chat=1)
        assert "Nobody matches" in w.transport.last(1).text
        await w.command(1, "broadcast", "all", reply_to=1, reply_chat=1)
        await w.press(1, data=w.transport.last(1).keyboard[0][1].data)
        assert w.store.broadcast(1)["status"] == "cancelled"
        assert w.transport.copies == []

    w.run(scenario())


def test_broadcast_button_needs_admin(world):
    w = world()

    async def scenario():
        await w.start(5)
        await w.command(1, "broadcast", "all", reply_to=1, reply_chat=1)
        await w.engine.on_callback(incoming(5, data="bc:1:y", callback_id="q", message_id=1))
        assert w.store.broadcast(1)["status"] == "draft"

    w.run(scenario())


def test_reload_keeps_old_config_on_errors(world, tmp_path):
    path = tmp_path / "funnel.yaml"
    path.write_text(
        "bot: {admins: [1], language: en}\npayments: {stars: true}\n"
        "products: {p: {title: P, prices: {XTR: 5}}}\n"
        "steps:\n  a:\n    text: new version\n    pay: p\n",
        encoding="utf-8",
    )
    w = world()
    w.engine.funnel_path = str(path)

    async def scenario():
        await w.command(1, "reload")
        assert "Reloaded: 1 steps, 1 products" in w.transport.last(1).text
        assert w.engine.funnel.start == "a"
        path.write_text("steps: {}\n", encoding="utf-8")
        await w.command(1, "reload")
        assert "old version keeps running" in w.transport.last(1).text
        assert w.engine.funnel.start == "a"

    w.run(scenario())


def test_payments_listing(world):
    w = world()

    async def scenario():
        await w.command(1, "payments")
        assert w.transport.last(1).text == "No payments yet."
        await buy_club(w, 5)
        await w.command(1, "payments")
        assert "user 5" in w.transport.last(1).text

    w.run(scenario())


def test_unknown_admin_command(world):
    w = world()

    async def scenario():
        await w.command(1, "nonsense")
        assert "Admin commands" in w.transport.last(1).text

    w.run(scenario())


def test_nudge_once_and_skipped_when_owned(world):
    def mutate(raw):
        raw["steps"]["offer"]["nudges"] = [
            {"after": "2h", "text": "Still here?", "buttons": [[{"text": "Club", "pay": "club"}]]},
            {"after": "1d", "text": "Last chance", "buttons": [[{"text": "Club", "pay": "club"}]]},
        ]

    w = world(mutate)

    async def scenario():
        await w.start(5)
        await w.press(5, "Offer")
        await w.start(6)
        await w.press(6, "Offer")
        await w.tick(3 * 3600)
        assert w.transport.texts(5).count("Still here?") == 1
        await w.tick(600)
        assert w.transport.texts(5).count("Still here?") == 1
        await w.press(6, "Club")
        await w.press(6, "Pay now")
        await w.pay_stars(6, charge="c6")
        await w.press(6, data="g:offer")
        await w.tick(2 * DAY)
        assert "Last chance" in w.transport.texts(5)
        assert "Last chance" not in w.transport.texts(6)

    w.run(scenario())


def test_nudge_waits_for_open_checkout(world):
    def mutate(raw):
        raw["steps"]["offer"]["nudges"] = [{"after": "20m", "text": "Nudge"}]

    w = world(mutate)

    async def scenario():
        await w.start(5)
        await w.press(5, "Offer")
        await w.press(5, "Club")
        await w.press(5, "Pay now")
        await w.tick(1800)
        assert "Nudge" not in w.transport.texts(5)
        await w.tick(2 * 3600)
        assert "Nudge" in w.transport.texts(5)

    w.run(scenario())


def test_test_payments_do_not_count_as_revenue(world):
    def mutate(raw):
        raw["bot"]["test_mode"] = True

    w = world(mutate)

    async def scenario():
        await w.start(1)
        await w.press(1, "Offer")
        await w.press(1, "Club")
        await w.press(1, "Test payment")
        await w.command(1, "stats")
        text = w.transport.last(1).text
        assert "Buyers: 0" in text and "Revenue" not in text

    w.run(scenario())
