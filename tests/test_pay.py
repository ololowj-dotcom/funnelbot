from decimal import Decimal

from conftest import incoming

from funnelbot.fake import FakeProvider

DAY = 86400


async def open_club(w, uid=5):
    await w.start(uid)
    await w.press(uid, "Offer")
    await w.press(uid, "Club")


def test_product_card_single_method_pay_now(world):
    w = world()

    async def scenario():
        await open_club(w)
        message = w.transport.last(5)
        assert "<b>Club</b>" in message.text and "Closed channel" in message.text
        labels = [b.text for b in w.transport.buttons(5)]
        assert labels == ["Pay now — 500 ⭐", "← Back"]
        assert w.transport.buttons(5)[0].style == "success"

    w.run(scenario())


def test_card_back_returns_to_step(world):
    w = world()

    async def scenario():
        await open_club(w)
        await w.press(5, "Back")
        assert w.transport.last(5).text == "Choose"

    w.run(scenario())


def test_stars_payment_delivers_channel_link_and_next_step(world):
    w = world()

    async def scenario():
        await open_club(w)
        await w.press(5, "Pay now")
        chat, invoice = w.transport.invoices[-1]
        assert chat == 5 and invoice.currency == "XTR" and invoice.amount == 500 and invoice.provider_token is None
        await w.pay_stars(5)
        texts = w.transport.texts(5)
        assert "Payment received. Thank you!" in texts
        assert any("https://t.me/+link100123" in t and "until" in t for t in texts)
        assert w.transport.last(5).text == "Thanks"
        grant = w.store.user_grants(5)[0]
        assert grant["expires_at"] == w.clock.t + 30 * DAY and grant["status"] == "active"
        payment = w.store.user_payments(5)[0]
        assert payment["status"] == "paid" and payment["delivered"] == 1 and payment["charge_id"] == "ch1"

    w.run(scenario())


def test_duplicate_success_does_not_deliver_twice(world):
    w = world()

    async def scenario():
        await open_club(w)
        await w.press(5, "Pay now")
        await w.pay_stars(5)
        count = len(w.transport.to(5))
        _, invoice = w.transport.invoices[-1]
        await w.engine.on_successful_payment(incoming(5), invoice.payload, "ch1", "XTR", 500)
        assert len(w.transport.to(5)) == count
        assert len(w.store.user_grants(5)) == 1

    w.run(scenario())


def test_link_is_created_once_per_chat(world):
    w = world()

    async def scenario():
        for uid in (5, 6):
            await open_club(w, uid)
            await w.press(uid, "Pay now")
            await w.pay_stars(uid, charge=f"c{uid}")
        assert w.transport.link_calls == 1

    w.run(scenario())


def test_message_product_and_file_cache(world, tmp_path):
    (tmp_path / "g.txt").write_text("guide", encoding="utf-8")

    def mutate(raw):
        raw["products"]["guide"]["access"] = [{"message": {"text": "Hello {first_name}", "file": "g.txt"}}]

    w = world(mutate)

    async def scenario():
        for uid in (5, 6):
            await w.start(uid)
            await w.press(uid, "Offer")
            await w.press(uid, "Guide")
            await w.press(uid, "Pay now")
            await w.pay_stars(uid, charge=f"c{uid}")
            assert "Hello User%d" % uid in w.transport.texts(uid)
        assert w.transport.files[0][1].endswith("g.txt")
        assert w.transport.files[1][1] == "file_id:cached-1"

    w.run(scenario())


def test_manager_product_sends_card(world):
    def mutate(raw):
        raw["products"]["guide"]["access"] = [{"manager": {"text": "We will call you"}}]

    w = world(mutate)

    async def scenario():
        await w.start(5, username="bob")
        await w.press(5, "Offer")
        await w.press(5, "Guide")
        await w.press(5, "Pay now")
        await w.pay_stars(5)
        card = w.transport.last(-100500).text
        assert "New paid order" in card and "Guide" in card and "via stars" in card
        assert "We will call you" in w.transport.texts(5)

    w.run(scenario())


def test_pre_checkout_rejects_wrong_amount_and_stranger(world):
    w = world()

    async def scenario():
        await open_club(w)
        await w.press(5, "Pay now")
        _, invoice = w.transport.invoices[-1]
        assert await w.engine.pre_checkout(5, invoice.payload, "XTR", 1)
        assert await w.engine.pre_checkout(6, invoice.payload, "XTR", 500)
        assert await w.engine.pre_checkout(5, "p999", "XTR", 500)
        assert await w.engine.pre_checkout(5, invoice.payload, "XTR", 500) is None
        await w.pay_stars(5)
        assert await w.engine.pre_checkout(5, invoice.payload, "XTR", 500)

    w.run(scenario())


def test_unmatched_payment_alerts_manager(world):
    w = world()

    async def scenario():
        await w.engine.on_successful_payment(incoming(9), "p777", "chX", "XTR", 100)
        assert "UNMATCHED PAYMENT" in w.transport.last(-100500).text

    w.run(scenario())


def test_join_request_approves_payer_and_declines_others(world):
    w = world()

    async def scenario():
        await open_club(w)
        await w.press(5, "Pay now")
        await w.pay_stars(5)
        await w.engine.on_join_request(-100123, 5, 5)
        await w.engine.on_join_request(-100123, 6, 6)
        await w.engine.on_join_request(-100999, 7, 7)
        assert w.transport.approved == [(-100123, 5)]
        assert w.transport.declined == [(-100123, 6)]
        assert w.store.user_grants(5)[0]["joined"] == 1
        assert "Welcome" in w.transport.last(5).text
        assert "No active access" in w.transport.last(6).text
        assert w.transport.to(7) == []

    w.run(scenario())


def test_expired_grant_declines_join(world):
    w = world()

    async def scenario():
        await open_club(w)
        await w.press(5, "Pay now")
        await w.pay_stars(5)
        w.clock.advance(31 * DAY)
        await w.engine.on_join_request(-100123, 5, 5)
        assert w.transport.declined == [(-100123, 5)]

    w.run(scenario())


def test_reminders_then_expiry_removes_member(world):
    w = world()

    async def scenario():
        await open_club(w)
        await w.press(5, "Pay now")
        await w.pay_stars(5)
        await w.engine.on_join_request(-100123, 5, 5)
        before = len(w.transport.to(5))
        await w.tick(20 * DAY)
        assert len(w.transport.to(5)) == before
        await w.tick(7 * DAY + 60)
        reminder = w.transport.last(5)
        assert "ends in 3 day" in reminder.text and reminder.keyboard[0][0].data == "p:club"
        await w.tick(60)
        assert w.transport.last(5) is reminder
        await w.tick(2 * DAY)
        assert "ends in 1 day" in w.transport.last(5).text
        await w.tick(DAY + 10)
        assert w.transport.removed == [(-100123, 5)]
        assert "has ended" in w.transport.last(5).text
        assert w.store.user_grants(5)[0]["status"] == "ended"
        await w.tick(DAY)
        assert w.transport.removed == [(-100123, 5)]

    w.run(scenario())


def test_missed_reminders_send_only_the_latest(world):
    w = world()

    async def scenario():
        await open_club(w)
        await w.press(5, "Pay now")
        await w.pay_stars(5)
        count = len(w.transport.to(5))
        await w.tick(29 * DAY + 3600 * 12)
        assert len(w.transport.to(5)) == count + 1
        assert "ends in 1 day" in w.transport.last(5).text
        await w.tick(60)
        assert len(w.transport.to(5)) == count + 1

    w.run(scenario())


def test_removal_failure_is_retried_with_backoff(world):
    w = world()

    async def scenario():
        await open_club(w)
        await w.press(5, "Pay now")
        await w.pay_stars(5)
        w.transport.remove_failures = 2
        await w.tick(30 * DAY + 1)
        assert w.transport.removed == []
        assert w.store.user_grants(5)[0]["status"] == "active"
        await w.tick(30)
        assert w.transport.removed == []
        await w.tick(61)
        assert w.transport.removed == []
        await w.tick(125)
        assert w.transport.removed == [(-100123, 5)]
        assert w.store.user_grants(5)[0]["status"] == "ended"

    w.run(scenario())


def test_enforce_expiry_off_only_marks_ended(world):
    def mutate(raw):
        raw["bot"]["enforce_expiry"] = False

    w = world(mutate)

    async def scenario():
        await open_club(w)
        await w.press(5, "Pay now")
        await w.pay_stars(5)
        await w.tick(31 * DAY)
        assert w.transport.removed == []
        assert w.store.user_grants(5)[0]["status"] == "ended"

    w.run(scenario())


def test_renewal_extends_and_resets_reminders(world):
    w = world()

    async def scenario():
        await open_club(w)
        await w.press(5, "Pay now")
        await w.pay_stars(5)
        await w.engine.on_join_request(-100123, 5, 5)
        await w.tick(28 * DAY)
        first_end = w.store.user_grants(5)[0]["expires_at"]
        await w.press(5, data="p:club")
        await w.press(5, "Pay now")
        await w.pay_stars(5, charge="ch2")
        grant = w.store.user_grants(5)
        assert len(grant) == 1 and grant[0]["expires_at"] == first_end + 30 * DAY
        assert grant[0]["reminded"] == []
        assert any("is extended" in t for t in w.transport.texts(5))
        assert w.transport.link_calls == 1

    w.run(scenario())


def test_two_products_same_chat_keep_member(world):
    def mutate(raw):
        raw["products"]["guide"]["access"] = [{"channel": {"chat": -100123, "days": 90}}]

    w = world(mutate)

    async def scenario():
        for label in ("Club", "Guide"):
            await w.start(5)
            await w.press(5, "Offer")
            await w.press(5, label)
            await w.press(5, "Pay now")
            await w.pay_stars(5, charge=label)
        await w.tick(31 * DAY)
        assert w.transport.removed == []
        statuses = sorted(g["status"] for g in w.store.user_grants(5))
        assert statuses == ["active", "ended"]
        await w.tick(60 * DAY)
        assert w.transport.removed == [(-100123, 5)]

    w.run(scenario())


def test_delivery_is_retried_after_failure(world):
    w = world()

    async def scenario():
        await open_club(w)
        await w.press(5, "Pay now")
        original = w.transport.create_join_link
        calls = {"n": 0}

        async def flaky(chat, name):
            calls["n"] += 1
            if calls["n"] == 1:
                from funnelbot.transport import TransportError

                raise TransportError("not enough rights")
            return await original(chat, name)

        w.transport.create_join_link = flaky
        await w.pay_stars(5)
        payment = w.store.user_payments(5)[0]
        assert payment["status"] == "paid" and payment["delivered"] == 0
        assert "not enough rights" in w.transport.last(-100500).text
        texts_before = w.transport.texts(5).count("Payment received. Thank you!")
        await w.tick(30)
        assert w.store.user_payments(5)[0]["delivered"] == 0
        await w.tick(40)
        payment = w.store.user_payments(5)[0]
        assert payment["delivered"] == 1
        assert w.transport.texts(5).count("Payment received. Thank you!") == texts_before
        assert any("t.me/+link100123" in t for t in w.transport.texts(5))
        assert len(w.store.user_grants(5)) == 1

    w.run(scenario())


def yookassa(raw):
    raw["payments"]["yookassa"] = {"shop_id": "1", "secret_key": "k", "return_url": "https://t.me/x"}
    raw["products"]["club"]["prices"] = {"XTR": 500, "RUB": 4900}


def test_two_methods_show_chooser(world):
    w = world(yookassa, {"yookassa": FakeProvider()})

    async def scenario():
        await open_club(w)
        labels = [b.text for b in w.transport.buttons(5)]
        assert labels == ["Telegram Stars — 500 ⭐", "YooKassa — 4900 ₽", "← Back"]
        assert "Choose a payment method" in w.transport.last(5).text

    w.run(scenario())


def test_yookassa_link_poll_and_delivery(world):
    provider = FakeProvider()
    w = world(yookassa, {"yookassa": provider})

    async def scenario():
        await open_club(w)
        await w.press(5, "YooKassa")
        message = w.transport.last(5)
        assert message.keyboard[0][0].url == "https://pay.example/ext-1"
        assert message.keyboard[1][0].data.startswith("k:")
        assert provider.created[0][1] == Decimal("4900")
        await w.press(5, "I have paid")
        assert w.transport.callbacks[-1][2] is True
        provider.states["ext-1"] = "paid"
        await w.tick(30)
        assert w.store.user_payments(5)[0]["status"] == "paid"
        assert any("t.me/+link" in t for t in w.transport.texts(5))
        assert w.transport.last(5).text == "Thanks"

    w.run(scenario())


def test_yookassa_check_button_confirms_immediately(world):
    provider = FakeProvider()
    w = world(yookassa, {"yookassa": provider})

    async def scenario():
        await open_club(w)
        await w.press(5, "YooKassa")
        provider.states["ext-1"] = "paid"
        await w.press(5, "I have paid")
        assert w.store.user_payments(5)[0]["status"] == "paid"
        assert w.transport.callbacks[-1][1] == "Payment received. Thank you!"

    w.run(scenario())


def test_link_payment_reused_within_window(world):
    provider = FakeProvider()
    w = world(yookassa, {"yookassa": provider})

    async def scenario():
        await open_club(w)
        await w.press(5, "YooKassa")
        await w.press(5, data="p:club")
        await w.press(5, "YooKassa")
        assert len(provider.created) == 1
        assert len(w.store.user_payments(5)) == 1

    w.run(scenario())


def test_provider_failure_message_and_alert(world):
    provider = FakeProvider()
    provider.fail_create = True
    w = world(yookassa, {"yookassa": provider})

    async def scenario():
        await open_club(w)
        await w.press(5, "YooKassa")
        assert "not completed" in w.transport.last(5).text
        assert "refused to create a payment" in w.transport.last(-100500).text
        assert w.store.user_payments(5)[0]["status"] == "failed"

    w.run(scenario())


def test_canceled_payment_notifies_user(world):
    provider = FakeProvider()
    w = world(yookassa, {"yookassa": provider})

    async def scenario():
        await open_club(w)
        await w.press(5, "YooKassa")
        provider.states["ext-1"] = "failed"
        await w.tick(30)
        assert "not completed" in w.transport.last(5).text
        assert w.store.user_payments(5)[0]["status"] == "failed"

    w.run(scenario())


def test_stale_link_payment_expires_and_late_payment_still_counts(world):
    provider = FakeProvider()
    w = world(yookassa, {"yookassa": provider})

    async def scenario():
        await open_club(w)
        await w.press(5, "YooKassa")
        await w.tick(2 * DAY)
        assert w.store.user_payments(5)[0]["status"] == "expired"
        assert "expired" in w.transport.last(5).text
        assert await w.engine.finalize_payment(1)
        assert w.store.user_payments(5)[0]["status"] == "paid"

    w.run(scenario())


def test_provider_outage_does_not_break_tick(world):
    provider = FakeProvider()
    w = world(yookassa, {"yookassa": provider})

    async def scenario():
        await open_club(w)
        await w.press(5, "YooKassa")
        provider.fail_status = True
        await w.tick(30)
        assert w.store.user_payments(5)[0]["status"] == "pending"

    w.run(scenario())


def manual(raw):
    raw["payments"]["manual"] = {"text": "Send to card 1111", "currency": "RUB"}
    raw["products"]["club"]["prices"] = {"XTR": 500, "RUB": 4900}


def test_manual_payment_approve(world):
    w = world(manual)

    async def scenario():
        await open_club(w)
        await w.press(5, "Bank transfer")
        assert "Send to card 1111" in w.transport.last(5).text and "4900 ₽" in w.transport.last(5).text
        await w.engine.on_photo(incoming(5, message_id=55, photo="p"))
        assert "manager will confirm" in w.transport.last(5).text
        assert w.transport.copies == [(-100500, 5, 55)]
        card = w.transport.last(-100500)
        assert [b.style for b in card.keyboard[0]] == ["success", "danger"]
        approve = card.keyboard[0][0].data
        await w.engine.on_callback(incoming(1, chat_id=-100500, data=approve, message_id=card.message_id, callback_id="x"))
        assert w.store.user_payments(5)[0]["status"] == "paid"
        assert "Your payment is confirmed." in w.transport.texts(5)
        assert any("t.me/+link" in t for t in w.transport.texts(5))
        again = incoming(1, chat_id=-100500, data=approve, message_id=card.message_id, callback_id="y")
        await w.engine.on_callback(again)
        assert w.transport.callbacks[-1][1] == "Already processed"

    w.run(scenario())


def test_manual_payment_reject_and_permissions(world):
    w = world(manual)

    async def scenario():
        await open_club(w)
        await w.press(5, "Bank transfer")
        await w.engine.on_photo(incoming(5, message_id=55, photo="p"))
        card = w.transport.last(-100500)
        stranger = incoming(77, chat_id=77, data=card.keyboard[0][1].data, message_id=1, callback_id="z")
        await w.engine.on_callback(stranger)
        assert w.store.user_payments(5)[0]["status"] == "review"
        reject = incoming(1, chat_id=-100500, data=card.keyboard[0][1].data, message_id=card.message_id, callback_id="r")
        await w.engine.on_callback(reject)
        assert w.store.user_payments(5)[0]["status"] == "rejected"
        assert "could not confirm" in w.transport.last(5).text
        assert w.store.user_grants(5) == []

    w.run(scenario())


def test_photo_without_open_payment_is_hinted(world):
    w = world(manual)

    async def scenario():
        await w.start(5)
        await w.engine.on_photo(incoming(5, message_id=9, photo="p"))
        assert w.transport.last(5).text == "Please use the buttons."

    w.run(scenario())


def test_test_mode_admin_only(world):
    def mutate(raw):
        raw["bot"]["test_mode"] = True

    w = world(mutate)

    async def scenario():
        await open_club(w, 1)
        assert any("Test payment" in b.text for b in w.transport.buttons(1))
        await w.press(1, "Test payment")
        assert w.store.user_payments(1)[0]["method"] == "test"
        assert w.store.user_grants(1)
        await open_club(w, 5)
        assert not any("Test payment" in b.text for b in w.transport.buttons(5))
        await w.press(5, data="m:club:test")
        assert w.store.user_payments(5) == []

    w.run(scenario())


def test_telegram_invoice_with_receipt(world):
    def mutate(raw):
        raw["payments"]["telegram"] = {
            "provider_token": "tok", "currency": "RUB", "need_email": True,
            "receipt": {"vat_code": 1, "contact_key": "email"},
        }
        raw["products"]["club"]["prices"] = {"RUB": 4900}
        raw["steps"]["welcome"]["buttons"] = []
        raw["steps"]["welcome"]["ask"] = {"key": "email", "type": "email"}
        raw["steps"]["welcome"]["next"] = "offer"

    w = world(mutate)

    async def scenario():
        await w.start(5)
        await w.say(5, "a@b.co")
        await w.press(5, "Club")
        await w.press(5, "Pay now")
        _, invoice = w.transport.invoices[-1]
        assert invoice.currency == "RUB" and invoice.amount == 490000 and invoice.provider_token == "tok"
        assert '"email": "a@b.co"' in invoice.provider_data and '"vat_code": 1' in invoice.provider_data
        await w.engine.on_successful_payment(incoming(5), invoice.payload, "tgch", "RUB", 490000, "a@b.co")
        assert w.store.user_payments(5)[0]["status"] == "paid"

    w.run(scenario())


def test_grants_survive_reload_of_funnel_without_product(world):
    w = world()

    async def scenario():
        await open_club(w)
        await w.press(5, "Pay now")
        await w.pay_stars(5)
        w.engine.funnel.products.pop("club")
        await w.tick(31 * DAY)
        assert w.transport.removed == [(-100123, 5)]
        assert "has ended" in w.transport.last(5).text

    w.run(scenario())
