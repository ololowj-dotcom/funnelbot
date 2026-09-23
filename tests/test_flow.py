from conftest import incoming

from funnelbot.core import normalize_answer
from funnelbot.schema import Ask


def test_start_shows_first_step(world):
    w = world()

    async def scenario():
        await w.start(5)
        message = w.transport.last(5)
        assert message.text == "Hi User5"
        assert [b.text for b in w.transport.buttons(5)] == ["Offer"]
        assert w.store.user(5)["step"] == "welcome"

    w.run(scenario())


def test_html_is_escaped_in_names(world):
    w = world()

    async def scenario():
        await w.start(5, first_name="<b>x</b>")
        assert w.transport.last(5).text == "Hi &lt;b&gt;x&lt;/b&gt;"

    w.run(scenario())


def test_goto_edits_message_and_back_returns(world):
    w = world()

    async def scenario():
        await w.start(5)
        first = w.transport.last(5).message_id
        await w.press(5, "Offer")
        assert len(w.transport.to(5)) == 1
        assert w.transport.last(5).edited and w.transport.last(5).text == "Choose"
        await w.press(5, "Back")
        assert w.transport.last(5).text == "Hi User5"
        assert w.transport.last(5).message_id == first

    w.run(scenario())


def test_button_styles_reach_keyboard(world):
    w = world()

    async def scenario():
        await w.start(5)
        await w.press(5, "Offer")
        styles = {b.text: b.style for b in w.transport.buttons(5)}
        assert styles["Guide"] == "success"
        assert styles["Club"] == "success"
        assert styles["Back"] is None

    w.run(scenario())


def test_home_button_resets(world):
    w = world(lambda raw: raw["steps"]["offer"]["buttons"].append([{"text": "Home", "home": True}]))

    async def scenario():
        await w.start(5)
        await w.press(5, "Offer")
        await w.press(5, "Home")
        assert w.transport.last(5).text == "Hi User5"
        assert w.store.user(5)["history"] == []

    w.run(scenario())


def test_consent_gate(world):
    def mutate(raw):
        raw["consent"] = {"text": "Agree please", "documents": [{"title": "Terms", "url": "https://x.io/t"}]}

    w = world(mutate)

    async def scenario():
        await w.start(5)
        assert w.transport.last(5).text == "Agree please"
        assert w.transport.last(5).keyboard[0][0].url == "https://x.io/t"
        await w.say(5, "hello")
        assert "press the button" in w.transport.last(5).text
        await w.press(5, "I agree")
        assert w.transport.last(5).text == "Hi User5"
        assert w.store.user(5)["consented_at"]
        assert w.transport.cleared

    w.run(scenario())


def test_ask_email_then_placeholder(world):
    def mutate(raw):
        raw["steps"]["welcome"] = {"text": "Your email?", "ask": {"key": "email", "type": "email"}, "next": "offer"}
        raw["steps"]["offer"]["text"] = "Thanks {email}"

    w = world(mutate)

    async def scenario():
        await w.start(5)
        await w.say(5, "nope")
        assert "email" in w.transport.last(5).text.lower()
        assert w.store.user(5)["step"] == "welcome"
        await w.say(5, "Me@Example.com")
        assert w.transport.last(5).text == "Thanks me@example.com"
        assert w.store.user(5)["answers"] == {"email": "me@example.com"}

    w.run(scenario())


def test_ask_choice_buttons(world):
    def mutate(raw):
        raw["steps"]["welcome"] = {
            "text": "Size?", "ask": {"key": "size", "type": "choice", "choices": ["S", "M", "L"]}, "next": "offer",
        }

    w = world(mutate)

    async def scenario():
        await w.start(5)
        assert [b.text for b in w.transport.buttons(5)] == ["S", "M", "L"]
        await w.press(5, "M")
        assert w.store.user(5)["answers"]["size"] == "M"
        assert w.transport.last(5).text == "Choose"

    w.run(scenario())


def test_step_without_input_gets_hint(world):
    w = world()

    async def scenario():
        await w.start(5)
        await w.say(5, "random")
        assert w.transport.last(5).text == "Please use the buttons."

    w.run(scenario())


def test_chain_autoadvance_and_wait(world):
    def mutate(raw):
        raw["steps"]["welcome"] = {"text": "One", "next": "mid"}
        raw["steps"]["mid"] = {"text": "Two", "next": "offer", "wait": "10m"}

    w = world(mutate)

    async def scenario():
        await w.start(5)
        assert w.transport.texts(5) == ["One", "Two"]
        await w.tick(300)
        assert w.transport.last(5).text == "Two"
        await w.tick(400)
        assert w.transport.last(5).text == "Choose"

    w.run(scenario())


def test_source_saved_once(world):
    w = world()

    async def scenario():
        await w.start(5, payload="ads1")
        await w.start(5, payload="other")
        assert w.store.user(5)["source"] == "ads1"

    w.run(scenario())


def test_removed_step_falls_back_to_start(world):
    w = world()

    async def scenario():
        await w.start(5)
        await w.press(5, data="g:ghost")
        assert w.transport.last(5).text == "Hi User5"

    w.run(scenario())


def test_manager_button_sends_card_once(world):
    def mutate(raw):
        raw["steps"]["welcome"]["buttons"].append([{"text": "Manager", "manager": True}])

    w = world(mutate)

    async def scenario():
        await w.start(5, username="bob")
        await w.press(5, "Manager", username="bob")
        await w.press(5, data="mg", username="bob")
        cards = w.transport.to(-100500)
        assert len(cards) == 1 and "@bob" in cards[0].text
        assert w.transport.last(5).text.startswith("A manager")

    w.run(scenario())


def test_normalize_answers():
    assert normalize_answer(Ask("k", "phone"), "12345") is None
    assert normalize_answer(Ask("k", "phone"), "+7 900 123 45 67") == "+79001234567"
    assert normalize_answer(Ask("k", "number"), "3,50") == "3.5"
    assert normalize_answer(Ask("k", "number"), "abc") is None
    assert normalize_answer(Ask("k", "regex", regex=r"\d{3}"), "123") == "123"
    assert normalize_answer(Ask("k", "regex", regex=r"\d{3}"), "12") is None
    assert normalize_answer(Ask("k", "text"), "  ") is None
    assert normalize_answer(Ask("k", "choice", choices=["Yes"]), "yes") == "Yes"


def test_blocked_user_marked(world):
    w = world()

    async def scenario():
        w.transport.blocked.add(5)
        await w.start(5)
        assert w.store.user(5)["blocked"] == 1
        w.transport.blocked.clear()
        await w.start(5)
        assert w.store.user(5)["blocked"] == 0

    w.run(scenario())


def test_incoming_helper_defaults():
    inc = incoming(7)
    assert inc.chat_id == 7 and inc.first_name == "User7"
