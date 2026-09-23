from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path
from typing import Callable, Optional

from .loader import FunnelError, load_funnel, parse_env_file
from .scaffold import create_project

Ask = Callable[[str, str], str]
Out = Callable[[str], None]
Checker = Callable[[str], str]


def default_folder() -> Path:
    if sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() == 0:
        return Path("/opt/funnelbot/bot")
    return Path.home() / "funnelbot"


def claim_link(username: str, code: str) -> str:
    return f"https://t.me/{username}?start=claim_{code}"


def ask_token(ask: Ask, out: Out, check: Checker) -> Optional[tuple]:
    out("\nStep 1 of 3: the bot token")
    out("  Open Telegram, find @BotFather, send /newbot, choose a name and a username ending in 'bot'.")
    out("  BotFather answers with a token that looks like 123456789:AAH... Paste it here.")
    for _ in range(4):
        token = ask("  Token (Enter to cancel)", "").strip()
        if not token:
            return None
        try:
            username = check(token)
        except ValueError as exc:
            out(f"  Telegram did not accept this token: {exc}")
            out("  Copy it again from BotFather (the whole line, with the colon).")
            continue
        out(f"  Accepted: your bot is @{username}")
        return token, username
    return None


def run_setup(folder: Path, ask: Ask, out: Out, check: Checker, install_service: Callable[[Path], bool],
              can_install_service: bool) -> int:
    folder = Path(folder)
    funnel = folder / "funnel.yaml"
    out("funnelbot setup: a few questions, about two minutes.")
    if funnel.exists():
        out(f"\nA funnel already exists in {folder}. Nothing was changed.")
        out("Start it with:  funnelbot run   (edit funnel.yaml any time, then press Reload funnel in /admin)")
        return 0
    found = ask_token(ask, out, check)
    if found is None:
        out("\nCancelled. Run `funnelbot setup` again when you have the token.")
        return 1
    token, username = found
    out("\nStep 2 of 3: language of the funnel and its texts")
    language = ask("  Language of the bot: ru or en", "ru").strip().lower()
    language = language if language in ("en", "ru") else "ru"
    out("\nStep 3 of 3: who manages the bot")
    out("  Easiest: press Enter. After the bot starts you will get a link; tapping it makes you the administrator.")
    admin = ask("  Or type your Telegram user id (send /id to the bot to see it)", "").strip()
    code = "" if admin else secrets.token_urlsafe(9)
    created = create_project(folder, language, token, admin, "")
    if code:
        env = folder / ".env"
        env.write_text(env.read_text(encoding="utf-8") + f"CLAIM_CODE={code}\n", encoding="utf-8")
    out(f"\nCreated {folder}: {', '.join(created)}")
    try:
        loaded = load_funnel(funnel, {**parse_env_file(folder / ".env")})
        out(f"The sample funnel is valid: {len(loaded.steps)} steps, {len(loaded.products)} products.")
    except FunnelError as exc:
        out(f"The sample funnel has a problem, please look at it: {exc}")
        return 1
    started = False
    if can_install_service:
        answer = ask("\nRun the bot in the background and start it on server boot? [Y/n]", "y").strip().lower()
        if answer in ("", "y", "yes"):
            started = install_service(funnel)
    out("\nAll set.")
    if started:
        out("The bot is running.")
    else:
        out(f"Start it with:  funnelbot run -f {funnel}")
    if code:
        out(f"\nBecome the administrator: open this link in Telegram and press Start:\n  {claim_link(username, code)}")
    else:
        out(f"\nOpen your bot: https://t.me/{username}  and send /admin")
    out("\nWhat next:")
    out("  - send /admin to your bot and press the Build the funnel button: steps, buttons, products and")
    out("    private channel access are created right there, with buttons")
    out("  - or edit the file by hand:  " + str(funnel))
    out("  - cards, YooKassa and crypto need keys: see docs/payments.md")
    return 0
