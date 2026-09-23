import pytest

from funnelbot.builder import (
    BuildError,
    Draft,
    button_dict,
    channel_item,
    dump_yaml,
    message_item,
    read_raw,
    write_checked,
)
from funnelbot.loader import parse_funnel


def blank():
    return {"bot": {"language": "en"}, "payments": {"stars": True}}


def valid(draft, tmp_path):
    return parse_funnel(draft.data, {}, tmp_path)


def test_build_a_funnel_from_nothing(tmp_path):
    draft = Draft(blank())
    welcome = draft.add_step("Hello!")
    offer = draft.add_step("Choose")
    pid = draft.add_product("Club", "Closed channel", {"XTR": 500})
    draft.add_access(pid, channel_item(-100123, 30))
    draft.add_button(welcome, button_dict("See offer", "goto", offer, "blue"))
    draft.add_button(offer, button_dict("Buy", "pay", pid, "green"))
    funnel = valid(draft, tmp_path)
    assert funnel.start == welcome
    assert funnel.products[pid].access[0].remind == [3, 1]
    assert funnel.steps[offer].buttons[0][0].style == "success"


def test_ids_are_generated_and_unique():
    draft = Draft(blank())
    assert [draft.add_step("a"), draft.add_step("b")] == ["step_1", "step_2"]
    draft.remove_step("step_2")
    assert draft.add_step("c") == "step_2"
    assert draft.add_product("P", "", {"XTR": 1}) == "product_1"


def test_cannot_delete_start_step():
    draft = Draft(blank())
    sid = draft.add_step("hi")
    with pytest.raises(BuildError):
        draft.remove_step(sid)


def test_removing_step_cleans_every_reference(tmp_path):
    draft = Draft(blank())
    a = draft.add_step("a")
    b = draft.add_step("b")
    c = draft.add_step("c")
    draft.add_button(a, button_dict("to b", "goto", b))
    draft.add_button(a, button_dict("to c", "goto", c))
    draft.add_nudge(a, "1h", "ping")
    draft.set_question(c, "email", a)
    draft.steps[c]["paid"] = b
    draft.remove_step(b)
    assert [x["text"] for _, _, x in draft.buttons_of(a)] == ["to c"]
    assert all(button["goto"] != b for n in draft.steps[a]["nudges"] for row in n["buttons"] for button in row)
    assert "paid" not in draft.steps[c]
    assert valid(draft, tmp_path)


def test_removing_product_cleans_buttons_and_pay(tmp_path):
    draft = Draft(blank())
    a = draft.add_step("a")
    pid = draft.add_product("P", "", {"XTR": 5})
    draft.add_button(a, button_dict("buy", "pay", pid))
    draft.add_nudge(a, "2h", "buy now")
    draft.steps[a]["pay"] = pid
    draft.remove_product(pid)
    step = draft.steps[a]
    assert "buttons" not in step and "pay" not in step
    assert "buttons" not in step["nudges"][0]
    assert valid(draft, tmp_path)


def test_nudge_copies_step_buttons_and_can_be_removed():
    draft = Draft(blank())
    a = draft.add_step("a")
    draft.add_button(a, button_dict("go", "goto", a))
    draft.add_nudge(a, "3h", "hey")
    assert draft.steps[a]["nudges"][0]["buttons"] == draft.steps[a]["buttons"]
    draft.steps[a]["buttons"][0][0]["text"] = "changed"
    assert draft.steps[a]["nudges"][0]["buttons"][0][0]["text"] == "go"
    draft.remove_nudge(a, 0)
    assert "nudges" not in draft.steps[a]
    with pytest.raises(BuildError):
        draft.remove_nudge(a, 0)


def test_question_replaces_buttons_and_keys_stay_unique(tmp_path):
    draft = Draft(blank())
    a = draft.add_step("a")
    b = draft.add_step("b")
    c = draft.add_step("c")
    draft.add_button(a, button_dict("x", "goto", b))
    assert draft.set_question(a, "email", b) == "email"
    assert "buttons" not in draft.steps[a] and draft.steps[a]["next"] == b
    assert draft.set_question(b, "email", c) == "email_2"
    with pytest.raises(BuildError):
        draft.add_button(a, button_dict("y", "goto", c))
    assert valid(draft, tmp_path)
    draft.clear_question(a)
    assert "ask" not in draft.steps[a] and "next" not in draft.steps[a]


def test_button_removal_tidies_rows():
    draft = Draft(blank())
    a = draft.add_step("a")
    draft.add_button(a, button_dict("1", "manager"))
    draft.add_button(a, button_dict("2", "back"))
    draft.remove_button(a, 0, 0)
    assert draft.steps[a]["buttons"] == [[{"text": "2", "back": True}]]
    draft.remove_button(a, 0, 0)
    assert "buttons" not in draft.steps[a]
    with pytest.raises(BuildError):
        draft.remove_button(a, 0, 0)


def test_price_and_access_editing():
    draft = Draft(blank())
    pid = draft.add_product("P", "d", {"XTR": 100})
    draft.set_price(pid, "RUB", 900)
    draft.remove_price(pid, "XTR")
    with pytest.raises(BuildError):
        draft.remove_price(pid, "RUB")
    draft.add_access(pid, message_item("hello", "file_id:ABC"))
    draft.add_access(pid, {"manager": {"text": "ok"}})
    draft.remove_access(pid, 0)
    assert draft.products[pid]["access"] == [{"manager": {"text": "ok"}}]
    with pytest.raises(BuildError):
        draft.remove_access(pid, 5)


def test_channel_item_reminders_follow_duration():
    assert channel_item(-1, 30)["channel"]["remind_days"] == [3, 1]
    assert channel_item(-1, 3)["channel"]["remind_days"] == [1]
    assert "remind_days" not in channel_item(-1, 1)["channel"]
    assert channel_item(-1, None) == {"channel": {"chat": -1}}


def test_button_dict_colors():
    assert button_dict("x", "pay", "p", "green")["style"] == "success"
    assert button_dict("x", "pay", "p", "red")["style"] == "danger"
    assert "style" not in button_dict("x", "pay", "p", "plain")


def test_write_checked_backs_up_and_rejects_invalid(tmp_path):
    path = tmp_path / "funnel.yaml"
    draft = Draft(blank())
    a = draft.add_step("first")
    path.write_text(dump_yaml(draft.data), encoding="utf-8")
    data = read_raw(path)
    Draft(data).set_text(a, "second")
    funnel = write_checked(path, data)
    assert funnel.steps[a].text == "second"
    assert "first" in (tmp_path / "funnel.yaml.bak").read_text(encoding="utf-8")
    bad = read_raw(path)
    bad["steps"][a]["buttons"] = [[{"text": "x", "goto": "ghost"}]]
    with pytest.raises(BuildError, match="unknown step 'ghost'"):
        write_checked(path, bad)
    assert read_raw(path)["steps"][a]["text"] == "second"
    assert not (tmp_path / "funnel.yaml.tmp").exists()


def test_env_placeholders_survive_a_round_trip(tmp_path):
    path = tmp_path / "funnel.yaml"
    path.write_text(
        'bot:\n  admins: ["${ADMIN_ID:-}"]\npayments: {stars: true}\nsteps:\n  a: {text: hi}\n', encoding="utf-8")
    data = read_raw(path)
    Draft(data).add_step("more")
    write_checked(path, data)
    assert "${ADMIN_ID:-}" in path.read_text(encoding="utf-8")
