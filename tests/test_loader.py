from decimal import Decimal

import pytest

from funnelbot.loader import FunnelError, Problems, interpolate, load_funnel, parse_env_file
from funnelbot.schema import parse_duration


def errors(build, raw, env=None):
    with pytest.raises(FunnelError) as info:
        build(raw, env)
    return str(info.value)


def test_valid_funnel_loads(build, raw):
    funnel = build(raw)
    assert funnel.start == "welcome"
    assert funnel.products["club"].prices["XTR"] == Decimal(500)
    assert funnel.products["club"].access[0].remind == [3, 1]
    assert funnel.steps["offer"].buttons[1][0].style == "success"
    assert funnel.methods_for("club") == ["stars"]
    assert funnel.warnings == []


def test_parse_duration():
    assert parse_duration("30s") == 30
    assert parse_duration("2h") == 7200
    assert parse_duration("1d") == 86400
    assert parse_duration("5") is None
    assert parse_duration("0m") is None
    assert parse_duration(True) is None
    assert parse_duration(3) == 180


def test_unknown_key_suggests(build, raw):
    raw["steps"]["welcome"]["buton"] = []
    assert "did you mean 'buttons'" in errors(build, raw)


def test_all_errors_reported_at_once(build, raw):
    raw["steps"]["welcome"]["buttons"] = [[{"text": "X", "goto": "nowhere"}]]
    raw["steps"]["offer"]["buttons"] = [[{"text": "Y", "pay": "ghost"}]]
    text = errors(build, raw)
    assert "unknown step 'nowhere'" in text
    assert "unknown product 'ghost'" in text


def test_button_needs_one_action(build, raw):
    raw["steps"]["welcome"]["buttons"] = [[{"text": "X"}]]
    assert "exactly one of" in errors(build, raw)
    raw["steps"]["welcome"]["buttons"] = [[{"text": "X", "goto": "offer", "url": "https://a.b"}]]
    assert "exactly one of" in errors(build, raw)


def test_bad_style(build, raw):
    raw["steps"]["welcome"]["buttons"] = [[{"text": "X", "goto": "offer", "style": "green"}]]
    assert "primary" in errors(build, raw)


def test_icon_must_be_numeric(build, raw):
    raw["steps"]["welcome"]["buttons"] = [[{"text": "X", "goto": "offer", "icon": "star"}]]
    assert "custom emoji id" in errors(build, raw)
    raw["steps"]["welcome"]["buttons"] = [[{"text": "X", "goto": "offer", "icon": "5368324170671202286"}]]
    assert build(raw).steps["welcome"].buttons[0][0].icon == "5368324170671202286"


def test_button_row_limit(build, raw):
    raw["steps"]["welcome"]["buttons"] = [[{"text": str(i), "goto": "offer"} for i in range(9)]]
    assert "at most 8" in errors(build, raw)


def test_unknown_placeholder(build, raw):
    raw["steps"]["welcome"]["text"] = "Hi {nick}"
    assert "unknown placeholder {nick}" in errors(build, raw)


def test_placeholder_from_ask_key(build, raw):
    raw["steps"]["welcome"]["text"] = "Hi {city}"
    raw["steps"]["thanks"] = {"text": "x", "ask": {"key": "city"}, "next": "offer"}
    build(raw)


def test_ask_needs_next(build, raw):
    raw["steps"]["thanks"] = {"text": "x", "ask": {"key": "email", "type": "email"}}
    assert "needs `next`" in errors(build, raw)


def test_ask_regex_validated(build, raw):
    raw["steps"]["thanks"] = {"text": "x", "ask": {"key": "code", "type": "regex", "regex": "("}, "next": "offer"}
    assert "broken pattern" in errors(build, raw)


def test_choice_needs_options(build, raw):
    raw["steps"]["thanks"] = {"text": "x", "ask": {"key": "size", "type": "choice"}, "next": "offer"}
    assert "list of options" in errors(build, raw)


def test_price_without_method(build, raw):
    raw["products"]["club"]["prices"] = {"RUB": 100}
    assert "no configured payment method" in errors(build, raw)


def test_stars_price_must_be_whole(build, raw):
    raw["products"]["club"]["prices"] = {"XTR": 10.5}
    assert "whole numbers" in errors(build, raw)


def test_digital_goods_warning_for_non_stars(build, raw):
    raw["payments"]["yookassa"] = {"shop_id": "1", "secret_key": "k", "return_url": "https://t.me/x"}
    raw["products"]["club"]["prices"] = {"RUB": 100}
    funnel = build(raw)
    assert any("Bot Developer Terms" in w for w in funnel.warnings)


def test_warning_stays_when_stars_also_offered(build, raw):
    raw["payments"]["yookassa"] = {"shop_id": "1", "secret_key": "k", "return_url": "https://t.me/x"}
    raw["products"]["club"]["prices"] = {"RUB": 100, "XTR": 500}
    funnel = build(raw)
    assert any("Bot Developer Terms" in w for w in funnel.warnings)


def test_manager_button_requires_chat(build, raw):
    raw["bot"].pop("manager_chat")
    raw["steps"]["welcome"]["buttons"] = [[{"text": "Ask", "manager": True}]]
    assert "bot.manager_chat" in errors(build, raw)


def test_manual_requires_manager_chat(build, raw):
    raw["bot"].pop("manager_chat")
    raw["payments"]["manual"] = {"text": "Pay", "currency": "RUB"}
    raw["products"]["guide"]["prices"] = {"XTR": 100, "RUB": 50}
    assert "payment screenshots" in errors(build, raw)


def test_telegram_currency_xtr_rejected(build, raw):
    raw["payments"]["telegram"] = {"provider_token": "t", "currency": "XTR"}
    assert "Stars" in errors(build, raw)


def test_receipt_needs_contact(build, raw):
    raw["payments"]["yookassa"] = {
        "shop_id": "1", "secret_key": "k", "return_url": "https://t.me/x", "receipt": {"vat_code": 1},
    }
    raw["products"]["guide"]["prices"] = {"RUB": 50}
    assert "never asks for 'email'" in errors(build, raw)


def test_receipt_contact_from_ask(build, raw):
    raw["payments"]["yookassa"] = {
        "shop_id": "1", "secret_key": "k", "return_url": "https://t.me/x", "receipt": {"vat_code": 1},
    }
    raw["products"]["guide"]["prices"] = {"RUB": 50, "XTR": 100}
    raw["steps"]["welcome"]["buttons"] = []
    raw["steps"]["welcome"]["ask"] = {"key": "email", "type": "email"}
    raw["steps"]["welcome"]["next"] = "offer"
    assert build(raw)


def test_unreachable_and_dead_end_warnings(build, raw):
    raw["steps"]["island"] = {"text": "alone"}
    warnings = build(raw).warnings
    assert any("cannot be reached" in w for w in warnings)
    assert any("dead end" in w for w in warnings)


def test_unused_product_warning(build, raw):
    raw["products"]["extra"] = {"title": "E", "prices": {"XTR": 5}}
    assert any("not offered" in w for w in build(raw).warnings)


def test_reminder_must_be_less_than_days(build, raw):
    raw["products"]["club"]["access"][0]["channel"]["remind_days"] = [30]
    assert "smaller than days" in errors(build, raw)


def test_reminders_need_days(build, raw):
    raw["products"]["club"]["access"][0]["channel"].pop("days")
    assert "never ends" in errors(build, raw)


def test_remind_days_single_number(build, raw):
    raw["products"]["club"]["access"][0]["channel"]["remind_days"] = 3
    assert build(raw).products["club"].access[0].remind == [3]


def test_bot_texts_keys_checked(build, raw):
    raw["bot"]["texts"] = {"paid_thnaks": "x"}
    assert "did you mean 'paid_thanks'" in errors(build, raw)
    raw["bot"]["texts"] = {"paid_thanks": "Done"}
    assert build(raw).bot.texts == {"paid_thanks": "Done"}


def test_missing_media_file(build, raw):
    raw["steps"]["welcome"]["image"] = "missing.png"
    assert "file not found" in errors(build, raw)


def test_media_found_relative_to_funnel(build, raw, tmp_path):
    (tmp_path / "pic.png").write_bytes(b"x")
    raw["steps"]["welcome"]["image"] = "pic.png"
    assert build(raw).steps["welcome"].image == str(tmp_path / "pic.png")


def test_file_id_and_url_media(build, raw):
    raw["steps"]["welcome"]["image"] = "file_id:AgAC123"
    assert build(raw).steps["welcome"].image == "file_id:AgAC123"


def test_env_interpolation_and_defaults(build, raw):
    raw["bot"]["language"] = "${LANG:-ru}"
    raw["payments"]["yookassa"] = {"shop_id": "${SHOP}", "secret_key": "k", "return_url": "https://t.me/x"}
    raw["products"]["guide"]["prices"] = {"XTR": 100, "RUB": 10}
    funnel = build(raw, {"SHOP": "42"})
    assert funnel.bot.language == "ru"
    assert funnel.payments.yookassa.shop_id == "42"


def test_missing_env_variable(build, raw):
    raw["payments"]["crypto"] = {"token": "${NOPE}"}
    assert "NOPE is not set" in errors(build, raw)


def test_interpolate_nested():
    problems = Problems()
    out = interpolate({"a": ["${X}", {"b": "${X}-${Y:-z}"}]}, {"X": "1"}, "", problems)
    assert out == {"a": ["1", {"b": "1-z"}]}
    assert problems.errors == []


def test_env_file_parse(tmp_path):
    (tmp_path / ".env").write_text("# c\nA=1\nexport B='two'\nC=\"three\"\n\nbad\n", encoding="utf-8")
    assert parse_env_file(tmp_path / ".env") == {"A": "1", "B": "two", "C": "three"}


def test_load_from_disk_with_env_file(tmp_path):
    (tmp_path / ".env").write_text("MANAGER=-100777\n", encoding="utf-8")
    (tmp_path / "f.yaml").write_text(
        "bot: {manager_chat: '${MANAGER}'}\n"
        "payments: {stars: true}\n"
        "products: {p: {title: P, prices: {XTR: 5}}}\n"
        "steps:\n  a:\n    text: hi\n    pay: p\n",
        encoding="utf-8",
    )
    funnel = load_funnel(tmp_path / "f.yaml", {})
    assert funnel.bot.manager_chat == -100777
    assert funnel.start == "a"
    assert any("not set" in w for w in funnel.warnings)


def test_missing_file_and_bad_yaml(tmp_path):
    with pytest.raises(FunnelError, match="not found"):
        load_funnel(tmp_path / "none.yaml", {})
    (tmp_path / "bad.yaml").write_text("a: [1, 2", encoding="utf-8")
    with pytest.raises(FunnelError, match="not valid YAML"):
        load_funnel(tmp_path / "bad.yaml", {})


def test_top_level_not_mapping(build):
    with pytest.raises(FunnelError):
        build(["x"])


def test_empty_admin_and_manager_from_env(build, raw):
    raw["bot"] = {"admins": [""], "manager_chat": ""}
    raw["products"]["club"]["access"] = []
    raw["products"]["guide"]["access"] = []
    funnel = build(raw)
    assert funnel.bot.admins == [] and funnel.bot.manager_chat is None


def test_paid_requires_offer(build, raw):
    raw["steps"]["welcome"]["paid"] = "thanks"
    assert "offers a product" in errors(build, raw)


def test_button_kinds(build, raw):
    raw["steps"]["offer"]["buttons"] = [
        [{"text": "Link", "url": "https://example.com"}, {"text": "Copy", "copy": "PROMO"}],
        [{"text": "Home", "home": True}, {"text": "Mgr", "manager": True}],
        [{"text": "Club", "pay": "club"}, {"text": "Guide", "pay": "guide"}],
    ]
    funnel = build(raw)
    row = funnel.steps["offer"].buttons[0]
    assert row[0].url and row[1].copy == "PROMO"


def test_pay_style_none_and_default(build, raw):
    assert build(raw).bot.pay_style == "success"
    raw["bot"]["pay_style"] = "none"
    assert build(raw).bot.pay_style is None
    raw["bot"]["pay_style"] = "danger"
    assert build(raw).bot.pay_style == "danger"
    raw["bot"]["pay_style"] = "pink"
    assert "primary" in errors(build, raw)
