import asyncio

import pytest
import yaml
from fakeapi import FakeTelegram

from funnelbot.cli import main
from funnelbot.doctor import FAIL, OK, WARN, diagnose
from funnelbot.loader import load_funnel
from funnelbot.preview import run_preview
from funnelbot.scaffold import render_template, service_unit


def test_init_creates_working_project(tmp_path, capsys):
    assert main(["init", str(tmp_path / "shop"), "--sample", "--token", "1:abc", "--admin", "5", "--manager", "-100777"]) == 0
    text = capsys.readouterr().out
    assert "funnelbot preview" in text and "/admin" in text
    folder = tmp_path / "shop"
    assert (folder / "funnel.yaml").is_file() and (folder / "files" / "guide.txt").is_file()
    env = (folder / ".env").read_text(encoding="utf-8")
    assert "BOT_TOKEN=1:abc" in env and "ADMIN_ID=5" in env and "MANAGER_CHAT=-100777" in env
    assert ".env" in (folder / ".gitignore").read_text(encoding="utf-8")
    funnel = load_funnel(folder / "funnel.yaml", {})
    assert funnel.bot.admins == [5] and funnel.bot.manager_chat == -100777
    assert "consult" in funnel.products


def test_init_without_manager_drops_manager_parts(tmp_path, capsys):
    assert main(["init", str(tmp_path), "--sample", "--token", "1:abc", "--admin", "5"]) == 0
    funnel = load_funnel(tmp_path / "funnel.yaml", {})
    assert funnel.bot.manager_chat is None and "consult" not in funnel.products
    assert not any(b.manager for s in funnel.steps.values() for row in s.buttons for b in row)
    assert "#manager" not in (tmp_path / "funnel.yaml").read_text(encoding="utf-8")


def test_init_without_admin_adds_claim_code(tmp_path, capsys):
    assert main(["init", str(tmp_path)]) == 0
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "CLAIM_CODE=" in env and len(env.split("CLAIM_CODE=")[1].strip()) >= 8
    assert "one-tap link" in capsys.readouterr().out
    assert load_funnel(tmp_path / "funnel.yaml", {}).bot.admins == []


def test_init_refuses_to_overwrite(tmp_path, capsys):
    main(["init", str(tmp_path)])
    original = (tmp_path / "funnel.yaml").read_text(encoding="utf-8")
    assert main(["init", str(tmp_path), "--lang", "ru"]) == 1
    assert (tmp_path / "funnel.yaml").read_text(encoding="utf-8") == original
    assert "already exists" in capsys.readouterr().out


@pytest.mark.parametrize("lang", ["en", "ru"])
@pytest.mark.parametrize("manager", [True, False])
@pytest.mark.parametrize("sample", [True, False])
def test_templates_always_validate(tmp_path, lang, manager, sample):
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "guide.txt").write_text("x", encoding="utf-8")
    (tmp_path / "funnel.yaml").write_text(render_template(lang, manager, sample), encoding="utf-8")
    env = {"MANAGER_CHAT": "-100777" if manager else "", "ADMIN_ID": "5"}
    funnel = load_funnel(tmp_path / "funnel.yaml", env)
    assert funnel.bot.language == lang
    assert funnel.warnings == [] or all("Terms" not in w for w in funnel.warnings)


def test_validate_prints_map_and_products(tmp_path, capsys):
    main(["init", str(tmp_path), "--sample", "--lang", "en", "--token", "1:a", "--admin", "5", "--manager", "-1001"])
    capsys.readouterr()
    assert main(["validate", "-f", str(tmp_path / "funnel.yaml")]) == 0
    text = capsys.readouterr().out
    assert "OK  funnel.yaml" in text and "welcome" in text and "pay:club" in text
    assert "club: Private club" in text and "channel -1001234567890 for 30 days" in text


def test_validate_reports_all_problems(tmp_path, capsys):
    (tmp_path / "funnel.yaml").write_text("steps:\n  a:\n    text: hi\n    buttons: [[{text: X, goto: b}]]\n", encoding="utf-8")
    assert main(["validate", "-f", str(tmp_path / "funnel.yaml")]) == 1
    text = capsys.readouterr().out
    assert "unknown step 'b'" in text and "Fix them" in text


def test_run_without_token_explains(tmp_path, capsys):
    main(["init", str(tmp_path), "--admin", "5"])
    capsys.readouterr()
    assert main(["run", "-f", str(tmp_path / "funnel.yaml")]) == 1
    assert "@BotFather" in capsys.readouterr().out


def test_no_command_shows_help(capsys):
    assert main([]) == 0
    assert "funnelbot init" in capsys.readouterr().out


def test_install_service_prints_unit(tmp_path, capsys):
    main(["init", str(tmp_path), "--admin", "5"])
    capsys.readouterr()
    assert main(["install-service", "-f", str(tmp_path / "funnel.yaml"), "--print"]) == 0
    text = capsys.readouterr().out
    assert "ExecStart=" in text and "-m funnelbot run" in text and "Restart=always" in text
    assert "systemctl daemon-reload" in text


def test_service_unit_shape(tmp_path):
    unit = service_unit("/usr/bin/python3", tmp_path / "funnel.yaml", tmp_path / "x.db", "bot")
    assert f"WorkingDirectory={tmp_path}" in unit and "User=bot" in unit and "--db" in unit
    assert unit.strip().endswith("WantedBy=multi-user.target")


def test_export_needs_database(tmp_path, capsys):
    main(["init", str(tmp_path), "--admin", "5"])
    capsys.readouterr()
    assert main(["export", "-f", str(tmp_path / "funnel.yaml"), str(tmp_path / "out.csv")]) == 1


def funnel_for_preview(tmp_path, manager=True):
    main(["init", str(tmp_path), "--sample", "--lang", "en", "--token", "1:a", "--admin", "5"] + (["--manager", "-100777"] if manager else []))
    return load_funnel(tmp_path / "funnel.yaml", {})


def test_preview_full_lifecycle(tmp_path, capsys):
    funnel = funnel_for_preview(tmp_path)
    capsys.readouterr()
    lines = []
    asyncio.run(run_preview(funnel, ["3", "1", "1", "1", ":pay", ":join", ":tick 27d", ":tick 3d", ":quit"], lines.append))
    text = "\n".join(lines)
    assert "🟩 I agree" in text and "INVOICE Private club: 500 XTR" in text
    assert "Payment received" in text and "APPROVED" in text
    assert "ends in 3 day" in text and "removed from" in text


def test_preview_manual_payment_and_admin(tmp_path):
    main(["init", str(tmp_path), "--sample", "--lang", "en", "--token", "1:a", "--admin", "5", "--manager", "-100777"])
    path = tmp_path / "funnel.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["payments"]["manual"] = {"text": "Send money to card 1111", "currency": "RUB"}
    data["products"]["guide"]["prices"] = {"XTR": 150, "RUB": 300}
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    funnel = load_funnel(path, {})
    lines = []
    script = ["3", "1", "2", "2", ":photo", ":approve", ":as admin", "/stats", ":quit"]
    asyncio.run(run_preview(funnel, script, lines.append))
    text = "\n".join(lines)
    assert "Bank transfer" in text and "Payment to review" in text
    assert "approved" in text.lower() and "Users:" in text


def test_preview_unknown_inputs(tmp_path):
    funnel = funnel_for_preview(tmp_path, manager=False)
    lines = []
    asyncio.run(run_preview(funnel, ["", "99", ":nonsense", ":tick x", ":state", ":help", ":quit"], lines.append))
    text = "\n".join(lines)
    assert "There is no such button" in text and "Unknown control" in text and "Usage: :tick" in text
    assert "Type a number to press a button" in text


def test_doctor_reports_rights_and_credentials(tmp_path):
    funnel = funnel_for_preview(tmp_path)

    async def scenario(**rights):
        api = FakeTelegram()
        api.rights = rights.get("rights", {})
        api.bot_status = rights.get("status", "administrator")
        await api.start()
        try:
            return await diagnose(funnel, "123:ABC", api.url)
        finally:
            await api.stop()

    good = asyncio.run(scenario())
    levels = {(lvl, subj) for lvl, subj, _ in good}
    assert (OK, "token") in levels and (OK, "chat -1001234567890") in levels and (OK, "manager_chat") in levels
    weak = asyncio.run(scenario(rights={"can_restrict_members": False}))
    assert any(lvl == FAIL and "can_restrict_members" in msg for lvl, _, msg in weak)
    outsider = asyncio.run(scenario(status="member"))
    assert any(lvl == FAIL and "not an administrator" in msg for lvl, _, msg in outsider)


def test_doctor_without_token(tmp_path):
    funnel = funnel_for_preview(tmp_path)
    findings = asyncio.run(diagnose(funnel, ""))
    assert findings[0][0] == FAIL and "BOT_TOKEN" in findings[0][2]


def test_doctor_warns_about_missing_stars(tmp_path):
    funnel = funnel_for_preview(tmp_path)
    funnel.payments.stars = None

    async def scenario():
        api = FakeTelegram()
        await api.start()
        try:
            return await diagnose(funnel, "123:ABC", api.url)
        finally:
            await api.stop()

    assert any(lvl == WARN and "Stars are off" in msg for lvl, _, msg in asyncio.run(scenario()))


def test_default_init_is_an_empty_funnel_ready_for_the_builder(tmp_path):
    assert main(["init", str(tmp_path), "--token", "1:a", "--admin", "5"]) == 0
    funnel = load_funnel(tmp_path / "funnel.yaml", {})
    assert list(funnel.steps) == ["welcome"] and funnel.products == {}
    assert funnel.warnings == []
    assert not (tmp_path / "files" / "guide.txt").exists()
