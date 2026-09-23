import asyncio

from fakeapi import FakeTelegram

from funnelbot.doctor import bot_username
from funnelbot.loader import load_funnel, parse_env_file
from funnelbot.wizard import claim_link, run_setup


class Script:
    def __init__(self, answers):
        self.answers = list(answers)
        self.asked = []
        self.lines = []

    def ask(self, question, default=""):
        self.asked.append(question)
        return self.answers.pop(0) if self.answers else default

    def out(self, text=""):
        self.lines.append(text)

    @property
    def text(self):
        return "\n".join(self.lines)


def checker(good="123:GOOD", name="shop_bot"):
    def check(token):
        if token != good:
            raise ValueError("Unauthorized")
        return name

    return check


def test_setup_happy_path_with_claim_link(tmp_path):
    script = Script(["123:GOOD", "ru", "", "y"])
    started = []
    code = run_setup(tmp_path / "bot", script.ask, script.out, checker(), lambda f: started.append(f) or True, True)
    assert code == 0
    env = parse_env_file(tmp_path / "bot" / ".env")
    assert env["BOT_TOKEN"] == "123:GOOD" and env["CLAIM_CODE"]
    assert load_funnel(tmp_path / "bot" / "funnel.yaml", env).bot.language == "ru"
    assert started == [tmp_path / "bot" / "funnel.yaml"]
    assert claim_link("shop_bot", env["CLAIM_CODE"]) in script.text
    assert "The bot is running." in script.text and "@shop_bot" in script.text


def test_setup_with_admin_id_and_no_service(tmp_path):
    script = Script(["123:GOOD", "en", "777"])
    code = run_setup(tmp_path / "bot", script.ask, script.out, checker(), lambda f: True, False)
    assert code == 0
    env = parse_env_file(tmp_path / "bot" / ".env")
    assert env["ADMIN_ID"] == "777" and "CLAIM_CODE" not in env
    assert "funnelbot run -f" in script.text and "send /admin" in script.text
    assert "start=claim_" not in script.text


def test_setup_retries_wrong_token_then_cancels(tmp_path):
    script = Script(["bad", "bad2", ""])
    code = run_setup(tmp_path / "bot", script.ask, script.out, checker(), lambda f: True, False)
    assert code == 1
    assert script.text.count("did not accept this token") == 2
    assert not (tmp_path / "bot" / "funnel.yaml").exists()


def test_setup_recovers_after_typo(tmp_path):
    script = Script(["oops", "123:GOOD", "xx", ""])
    assert run_setup(tmp_path / "bot", script.ask, script.out, checker(), lambda f: True, False) == 0
    assert parse_env_file(tmp_path / "bot" / ".env")["BOT_TOKEN"] == "123:GOOD"
    assert load_funnel(tmp_path / "bot" / "funnel.yaml", {"ADMIN_ID": ""}).bot.language == "ru"


def test_setup_declined_service(tmp_path):
    script = Script(["123:GOOD", "en", "", "n"])
    started = []
    run_setup(tmp_path / "bot", script.ask, script.out, checker(), lambda f: started.append(f) or True, True)
    assert started == [] and "funnelbot run -f" in script.text


def test_setup_does_not_touch_existing_project(tmp_path):
    (tmp_path / "bot").mkdir()
    (tmp_path / "bot" / "funnel.yaml").write_text("keep", encoding="utf-8")
    script = Script([])
    assert run_setup(tmp_path / "bot", script.ask, script.out, checker(), lambda f: True, False) == 0
    assert (tmp_path / "bot" / "funnel.yaml").read_text(encoding="utf-8") == "keep"
    assert "Nothing was changed" in script.text


def test_bot_username_against_fake_api():
    async def scenario():
        api = FakeTelegram()
        await api.start()
        try:
            return await bot_username("123:ABC", api.url)
        finally:
            await api.stop()

    assert asyncio.run(scenario()) == "funnel_test_bot"
