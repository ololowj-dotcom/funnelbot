import re
from pathlib import Path

from conftest import incoming

from funnelbot.owner import EN, RU
from funnelbot.texts import EN as TEXTS_EN
from funnelbot.texts import RU as TEXTS_RU

SRC = Path(__file__).resolve().parent.parent / "src" / "funnelbot"


def test_owner_tables_have_same_keys_and_placeholders():
    assert set(EN) == set(RU)
    pattern = re.compile(r"\{(\w+)\}")
    for key in EN:
        assert sorted(pattern.findall(EN[key])) == sorted(pattern.findall(RU[key])), key


def test_customer_tables_have_same_keys_and_placeholders():
    assert set(TEXTS_EN) == set(TEXTS_RU)
    pattern = re.compile(r"\{(\w+)\}")
    for key in TEXTS_EN:
        assert sorted(pattern.findall(TEXTS_EN[key])) == sorted(pattern.findall(TEXTS_RU[key])), key


def test_every_used_key_exists():
    used = set()
    for path in SRC.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        used |= set(re.findall(r'self\.o\(\s*"(\w+)"', text))
        used |= set(re.findall(r'self\.tx\(\s*"(\w+)"', text))
    dynamic = {f"status_{s}" for s in ("pending", "awaiting_proof", "review", "paid", "failed", "expired", "refunded", "rejected", "active", "ended")}
    dynamic |= {f"seg_{c}" for c in ("all", "paid", "unpaid", "active", "expired", "test")}
    missing = {k for k in used if k not in EN and k not in TEXTS_EN}
    assert not missing, missing
    assert dynamic <= set(EN)


def test_russian_is_the_default(build, raw):
    raw["bot"].pop("language")
    assert build(raw).bot.language == "ru"


def test_customer_flow_in_russian_by_default(world):
    def mutate(raw):
        raw["bot"].pop("language")

    w = world(mutate)

    async def scenario():
        await w.start(5)
        await w.say(5, "что-то")
        assert w.transport.last(5).text == "Пользуйтесь кнопками."
        await w.start(5)
        await w.press(5, "Offer")
        await w.press(5, "Club")
        assert w.transport.buttons(5)[0].text == "Оплатить — 500 ⭐"
        await w.press(5, "Оплатить")
        await w.pay_stars(5)
        assert "Оплата получена. Спасибо!" in w.transport.texts(5)
        assert any("Доступ к" in t and "активен" in t for t in w.transport.texts(5))

    w.run(scenario())


def test_admin_panel_in_russian(world):
    def mutate(raw):
        raw["bot"]["language"] = "ru"

    w = world(mutate)

    async def scenario():
        await w.command(1, "admin")
        labels = [b.text for row in w.transport.last(1).keyboard for b in row]
        assert labels[0] == "📊 Статистика" and "📣 Рассылка" in labels and "🩺 Проверка бота" in labels
        await w.press(1, "Статистика")
        assert "Пользователи:" in w.transport.last(1).text
        await w.press(1, "В панель")
        await w.press(1, "Платежи")
        assert w.transport.last(1).text == "Платежей пока нет."

    w.run(scenario())


def test_alerts_and_cards_in_russian(world):
    def mutate(raw):
        raw["bot"]["language"] = "ru"

    w = world(mutate)

    async def scenario():
        await w.engine.on_successful_payment(incoming(9), "p777", "chX", "XTR", 100)
        assert "ПЛАТЁЖ БЕЗ ЗАКАЗА" in w.transport.last(-100500).text
        await w.start(5)
        await w.engine.call_manager(w.store.user(5), 5)
        assert "Запрос менеджера" in w.transport.last(-100500).text

    w.run(scenario())


def test_statuses_are_translated(world):
    def mutate(raw):
        raw["bot"]["language"] = "ru"

    w = world(mutate)

    async def scenario():
        await w.start(5)
        w.store.add_payment(5, "club", "stars", "500", "XTR", "paid", w.clock.t)
        await w.command(1, "user", "5")
        assert "оплачен" in w.transport.last(1).text

    w.run(scenario())
