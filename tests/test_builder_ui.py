import pytest
from conftest import Clock, World, incoming

from funnelbot.builder import read_raw
from funnelbot.engine import Engine
from funnelbot.fake import RecordingTransport
from funnelbot.loader import load_funnel
from funnelbot.store import Store

BLANK = """
bot:
  language: en
  admins: [1]
  manager_chat: -100500
payments:
  stars: true
products: {}
start: welcome
steps:
  welcome:
    text: "Hi {first_name}"
"""


@pytest.fixture
def studio(tmp_path):
    def make(text=BLANK, with_file=True):
        path = tmp_path / "funnel.yaml"
        path.write_text(text, encoding="utf-8")
        funnel = load_funnel(path, {})
        transport = RecordingTransport()
        engine = Engine(funnel, Store(":memory:"), transport, {}, clock=Clock(),
                        funnel_path=str(path) if with_file else None, log=lambda m: None)
        world = World(engine, engine.store, transport, engine.clock)
        world.path = path
        return world

    return make


async def open_builder(w):
    await w.command(1, "admin")
    await w.press(1, "Build the funnel")


async def new_step(w, text):
    await w.press(1, data="ad:ws")
    await w.press(1, "New step")
    await w.say(1, text)
    return w.store.kv_get("bw:1")


def steps_of(w):
    return read_raw(w.path)["steps"]


def test_build_a_whole_funnel_in_the_bot_then_buy_it(studio):
    w = studio()

    async def scenario():
        await open_builder(w)
        assert "Steps: 1, products: 0" in w.transport.last(1).text

        await w.press(1, data="ad:ws")
        await w.press(1, "New step")
        await w.say(1, "Choose your plan")
        assert "Step step_1" in w.transport.last(1).text
        assert "Choose your plan" in steps_of(w)["step_1"]["text"]

        await w.press(1, data="ad:wp")
        await w.press(1, "New product")
        await w.say(1, "Club")
        await w.press(1, "Skip")
        await w.say(1, "500")
        assert "Club" in w.transport.last(1).text and "500 ⭐" in w.transport.last(1).text
        await w.press(1, "What they get")
        await w.press(1, "private channel")
        await w.say(1, "-100123")
        await w.press(1, "30 days")
        assert "access to channel -100123, 30 days" in w.transport.last(1).text
        product = read_raw(w.path)["products"]["product_1"]
        assert product["access"][0]["channel"] == {"chat": -100123, "days": 30, "remind_days": [3, 1]}

        await w.press(1, data="ad:ws")
        await w.press(1, "Choose your plan")
        await w.press(1, "➕ Button")
        await w.press(1, "Buy a product")
        await w.press(1, "Club")
        await w.say(1, "Join for 500")
        await w.press(1, "Green")
        assert "Join for 500" in w.transport.last(1).text

        await w.press(1, data="ad:ws")
        await w.press(1, "Hi {first_name}")
        await w.press(1, "➕ Button")
        await w.press(1, "Go to a step")
        await w.press(1, "Choose your plan")
        await w.say(1, "See the plans")
        await w.press(1, "Blue")

        assert w.engine.funnel.products["product_1"].access[0].chat == -100123
        await w.start(5)
        assert [b.text for b in w.transport.buttons(5)] == ["See the plans"]
        assert w.transport.buttons(5)[0].style == "primary"
        await w.press(5, "See the plans")
        buy = w.transport.buttons(5)[0]
        assert buy.text == "Join for 500" and buy.style == "success"
        await w.press(5, "Join for 500")
        await w.press(5, "Pay now")
        await w.pay_stars(5)
        assert any("t.me/+link100123" in t for t in w.transport.texts(5))

    w.run(scenario())


def test_file_stays_valid_and_keeps_a_backup(studio):
    w = studio()

    async def scenario():
        await open_builder(w)
        await new_step(w, "Second")
        assert load_funnel(w.path, {}).steps["step_1"].text == "Second"
        assert (w.path.parent / "funnel.yaml.bak").is_file()

    w.run(scenario())


def test_step_text_picture_and_start(studio):
    w = studio()

    async def scenario():
        await open_builder(w)
        await new_step(w, "Second")
        await w.press(1, "✏️ Text")
        await w.say(1, "Renamed")
        assert steps_of(w)["step_1"]["text"] == "Renamed"
        await w.press(1, "🖼 Picture")
        await w.engine.on_photo(incoming(1, file_id="PHOTO1", file_kind="photo", message_id=9))
        assert steps_of(w)["step_1"]["image"] == "file_id:PHOTO1"
        assert "Picture: yes" in w.transport.last(1).text
        await w.press(1, "🖼 Picture")
        await w.engine.on_photo(incoming(1, file_id="DOC1", file_kind="document", message_id=10))
        assert "Send it as a photo" in w.transport.last(1).text
        await w.press(1, "Cancel")
        await w.press(1, "🖼 Picture")
        await w.press(1, "Remove the picture")
        assert "image" not in steps_of(w)["step_1"]
        await w.press(1, "Make it the start")
        assert read_raw(w.path)["start"] == "step_1"

    w.run(scenario())


def test_buttons_link_manager_back_and_delete(studio):
    w = studio()

    async def scenario():
        await open_builder(w)
        await w.press(1, data="ad:ws")
        await w.press(1, "Hi {first_name}")
        await w.press(1, "➕ Button")
        await w.press(1, "Open a link")
        await w.say(1, "not a link")
        assert "not a link" in w.transport.last(1).text.lower() or "That is not a link" in w.transport.last(1).text
        await w.say(1, "https://example.com/x")
        await w.say(1, "Website")
        await w.press(1, "Plain")
        await w.press(1, "➕ Button")
        await w.press(1, "Call the manager")
        await w.say(1, "Ask us")
        await w.press(1, "Red")
        await w.press(1, "➕ Button")
        await w.press(1, "Back")
        rows = steps_of(w)["welcome"]["buttons"]
        assert rows[0][0] == {"text": "Website", "url": "https://example.com/x"}
        assert rows[1][0]["manager"] is True and rows[1][0]["style"] == "danger"
        assert rows[2][0]["back"] is True
        await w.press(1, "🗑 Button")
        await w.press(1, "Website")
        assert len(steps_of(w)["welcome"]["buttons"]) == 2
        await w.start(5)
        assert [b.text for b in w.transport.buttons(5)][0] == "Ask us"

    w.run(scenario())


def test_new_step_created_from_button_flow(studio):
    w = studio()

    async def scenario():
        await open_builder(w)
        await w.press(1, data="ad:ws")
        await w.press(1, "Hi {first_name}")
        await w.press(1, "➕ Button")
        await w.press(1, "Go to a step")
        await w.press(1, "➕ New step")
        await w.say(1, "About us")
        await w.say(1, "Learn more")
        await w.press(1, "Green")
        steps = steps_of(w)
        assert steps["step_1"]["text"] == "About us"
        assert steps["welcome"]["buttons"][0][0]["goto"] == "step_1"

    w.run(scenario())


def test_reminders(studio):
    w = studio()

    async def scenario():
        await open_builder(w)
        await w.press(1, data="ad:ws")
        await w.press(1, "Hi {first_name}")
        await w.press(1, "⏰ Reminders")
        await w.press(1, "after 3 hours")
        await w.say(1, "Still here?")
        assert steps_of(w)["welcome"]["nudges"] == [{"after": "3h", "text": "Still here?"}]
        await w.start(5)
        await w.tick(3 * 3600 + 5)
        assert "Still here?" in w.transport.texts(5)
        await w.press(1, "⏰ Reminders")
        await w.press(1, "🗑 3h")
        assert "nudges" not in steps_of(w)["welcome"]

    w.run(scenario())


def test_question_step(studio):
    w = studio()

    async def scenario():
        await open_builder(w)
        await new_step(w, "Thanks!")
        await w.press(1, data="ad:ws")
        await w.press(1, "Hi {first_name}")
        await w.press(1, "❓ Ask a question")
        await w.press(1, "Email")
        await w.press(1, "Thanks!")
        ask = steps_of(w)["welcome"]
        assert ask["ask"] == {"key": "email", "type": "email"} and ask["next"] == "step_1"
        await w.start(5)
        await w.say(5, "a@b.co")
        assert w.transport.last(5).text == "Thanks!"
        assert w.store.user(5)["answers"] == {"email": "a@b.co"}
        await w.press(1, "❓ Ask a question")
        await w.press(1, "Remove the question")
        assert "ask" not in steps_of(w)["welcome"]

    w.run(scenario())


def test_question_step_cannot_get_buttons(studio):
    w = studio()

    async def scenario():
        await open_builder(w)
        await new_step(w, "Thanks!")
        await w.press(1, data="ad:ws")
        await w.press(1, "Hi {first_name}")
        await w.press(1, "❓ Ask a question")
        await w.press(1, "Phone")
        await w.press(1, "Thanks!")
        await w.press(1, "➕ Button")
        assert "cannot have buttons" in w.transport.last(1).text

    w.run(scenario())


def test_question_needs_another_step(studio):
    w = studio()

    async def scenario():
        await open_builder(w)
        await w.press(1, data="ad:ws")
        await w.press(1, "Hi {first_name}")
        await w.press(1, "❓ Ask a question")
        await w.press(1, "Text")
        assert "need another step" in w.transport.last(1).text

    w.run(scenario())


def test_delete_step_and_start_is_protected(studio):
    w = studio()

    async def scenario():
        await open_builder(w)
        await new_step(w, "Extra")
        await w.press(1, "Delete step")
        await w.press(1, "Yes, delete")
        assert "step_1" not in steps_of(w)
        await w.press(1, "Hi {first_name}")
        assert not any("Delete step" in b.text for b in w.transport.buttons(1))

    w.run(scenario())


def test_product_editing(studio):
    w = studio()

    async def scenario():
        await open_builder(w)
        await w.press(1, data="ad:wp")
        await w.press(1, "New product")
        await w.say(1, "Guide")
        await w.say(1, "A short guide")
        await w.say(1, "150")
        assert "Description: A short guide" in w.transport.last(1).text
        await w.press(1, "✏️ Name")
        await w.say(1, "Better guide")
        assert read_raw(w.path)["products"]["product_1"]["title"] == "Better guide"
        await w.press(1, "What they get")
        await w.press(1, "message and a file")
        await w.say(1, "Here you go, {first_name}")
        await w.engine.on_photo(incoming(1, file_id="P", file_kind="photo", message_id=3))
        assert "as a document" in w.transport.last(1).text
        await w.engine.on_photo(incoming(1, file_id="DOC9", file_kind="document", message_id=4))
        item = read_raw(w.path)["products"]["product_1"]["access"][0]
        assert item == {"message": {"text": "Here you go, {first_name}", "files": ["file_id:DOC9"]}}
        await w.press(1, "What they get")
        await w.press(1, "request to the manager")
        await w.say(1, "We will call you")
        assert len(read_raw(w.path)["products"]["product_1"]["access"]) == 2
        await w.press(1, "Remove a gift")
        await w.press(1, "🗑 a message")
        assert len(read_raw(w.path)["products"]["product_1"]["access"]) == 1

    w.run(scenario())


def test_prices_validation_and_currency_rules(studio):
    w = studio()

    async def scenario():
        await open_builder(w)
        await w.press(1, data="ad:wp")
        await w.press(1, "New product")
        await w.say(1, "Guide")
        await w.press(1, "Skip")
        await w.say(1, "abc")
        assert "not a valid price" in w.transport.last(1).text
        await w.say(1, "10.5")
        assert "not a valid price" in w.transport.last(1).text
        await w.say(1, "-4")
        assert "not a valid price" in w.transport.last(1).text
        await w.say(1, "20")
        assert read_raw(w.path)["products"]["product_1"]["prices"] == {"XTR": 20}
        await w.press(1, "💰 Prices")
        await w.press(1, "XTR:")
        await w.say(1, "25")
        assert read_raw(w.path)["products"]["product_1"]["prices"] == {"XTR": 25}

    w.run(scenario())


def test_channel_id_validation_and_warning(studio):
    w = studio()
    w.transport.chat_problems[-100999] = "the bot is not an administrator of 'X'"

    async def scenario():
        await open_builder(w)
        await w.press(1, data="ad:wp")
        await w.press(1, "New product")
        await w.say(1, "Club")
        await w.press(1, "Skip")
        await w.say(1, "500")
        await w.press(1, "What they get")
        await w.press(1, "private channel")
        await w.say(1, "my channel")
        assert "not a channel id" in w.transport.last(1).text
        await w.say(1, "-100999")
        assert "not an administrator" in w.transport.last(1).text
        await w.press(1, "forever")
        item = read_raw(w.path)["products"]["product_1"]["access"][0]
        assert item == {"channel": {"chat": -100999}}

    w.run(scenario())


def test_delete_product_cleans_buttons(studio):
    w = studio()

    async def scenario():
        await open_builder(w)
        await w.press(1, data="ad:wp")
        await w.press(1, "New product")
        await w.say(1, "Club")
        await w.press(1, "Skip")
        await w.say(1, "500")
        await w.press(1, data="ad:ws")
        await w.press(1, "Hi {first_name}")
        await w.press(1, "➕ Button")
        await w.press(1, "Buy a product")
        await w.press(1, "Club")
        await w.say(1, "Buy")
        await w.press(1, "Green")
        assert "buttons" in steps_of(w)["welcome"]
        await w.press(1, data="ad:wp")
        await w.press(1, "Club")
        await w.press(1, "Delete product")
        await w.press(1, "Yes, delete")
        assert read_raw(w.path)["products"] == {}
        assert "buttons" not in steps_of(w)["welcome"]

    w.run(scenario())


def test_no_products_message_and_payment_settings(studio):
    w = studio()

    async def scenario():
        await open_builder(w)
        await w.press(1, data="ad:ws")
        await w.press(1, "Hi {first_name}")
        await w.press(1, "➕ Button")
        await w.press(1, "Buy a product")
        assert "no products yet" in w.transport.last(1).text
        await w.press(1, data="ad:wm")
        text = w.transport.last(1).text
        assert "Telegram Stars: on (XTR)" in text and "YooKassa: off" in text and "Test mode" in text
        await w.press(1, "Turn on test mode")
        assert read_raw(w.path)["bot"]["test_mode"] is True
        await w.press(1, "Switch language")
        assert read_raw(w.path)["bot"]["language"] == "ru"
        assert w.engine.funnel.bot.language == "ru"
        await w.press(1, "Сменить язык")
        assert w.engine.funnel.bot.language == "en"

    w.run(scenario())


def test_turning_stars_off_is_refused_when_products_need_it(studio):
    w = studio()

    async def scenario():
        await open_builder(w)
        await w.press(1, data="ad:wp")
        await w.press(1, "New product")
        await w.say(1, "Club")
        await w.press(1, "Skip")
        await w.say(1, "500")
        await w.press(1, data="ad:wm")
        await w.press(1, "Turn off Telegram Stars")
        assert "Could not save this change, nothing was changed" in w.transport.last(1).text
        assert read_raw(w.path)["payments"]["stars"] is True
        assert w.engine.funnel.payments.stars is not None

    w.run(scenario())


def test_no_product_creation_without_a_payment_method(studio):
    w = studio(BLANK.replace("stars: true", "{}").replace("payments:\n  {}", "payments: {}"))

    async def scenario():
        await open_builder(w)
        await w.press(1, data="ad:wm")
        await w.press(1, "Turn on Telegram Stars")
        await w.press(1, data="ad:wp")
        await w.press(1, "New product")
        assert "Send me the name" in w.transport.last(1).text

    w.run(scenario())


def test_view_as_customer_and_unavailable_builder(studio):
    w = studio()

    async def scenario():
        await open_builder(w)
        await w.press(1, "See it as a customer")
        assert w.transport.last(1).text == "Hi User1"

    w.run(scenario())

    n = studio(with_file=False)

    async def scenario2():
        await open_builder(n)
        await n.press(1, data="ad:ws")
        await n.press(1, "New step")
        await n.say(1, "x")
        assert "needs the funnel file" in n.transport.last(1).text

    n.run(scenario2())


def test_cancel_clears_pending_input(studio):
    w = studio()

    async def scenario():
        await open_builder(w)
        await w.press(1, data="ad:ws")
        await w.press(1, "New step")
        await w.press(1, "Cancel")
        await w.say(1, "should be ignored")
        assert list(steps_of(w)) == ["welcome"]

    w.run(scenario())


def test_builder_is_admin_only(studio):
    w = studio()

    async def scenario():
        await w.start(5)
        count = len(w.transport.to(5))
        await w.engine.on_callback(incoming(5, data="ad:w", callback_id="x", message_id=1))
        await w.engine.on_callback(incoming(5, data="ad:wn", callback_id="y", message_id=1))
        await w.say(5, "hello")
        assert list(steps_of(w)) == ["welcome"]
        assert len(w.transport.to(5)) == count + 1

    w.run(scenario())


def test_russian_builder(studio):
    w = studio(BLANK.replace("language: en", "language: ru"))

    async def scenario():
        await w.command(1, "admin")
        await w.press(1, "Собрать воронку")
        assert "Конструктор воронки" in w.transport.last(1).text
        await w.press(1, "Шаги")
        await w.press(1, "Новый шаг")
        assert "Пришлите текст сообщения" in w.transport.last(1).text

    w.run(scenario())


def test_manager_chat_can_be_set_from_a_group(studio):
    w = studio(BLANK.replace("  manager_chat: -100500\n", ""))

    async def scenario():
        await open_builder(w)
        await w.press(1, data="ad:wm")
        assert "Manager chat: no" in w.transport.last(1).text
        await w.command(1, "managerchat", chat_id=-100777)
        assert w.engine.funnel.bot.manager_chat == -100777
        assert read_raw(w.path)["bot"]["manager_chat"] == -100777
        assert "manager chat" in w.transport.last(-100777).text.lower()

    w.run(scenario())


def test_start_leaves_pending_builder_input(studio):
    w = studio()

    async def scenario():
        await open_builder(w)
        await w.press(1, data="ad:ws")
        await w.press(1, "New step")
        await w.start(1)
        await w.say(1, "not a step")
        assert list(steps_of(w)) == ["welcome"]

    w.run(scenario())
