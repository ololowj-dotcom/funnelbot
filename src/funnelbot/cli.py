from __future__ import annotations

import argparse
import asyncio
import logging
import os
import secrets
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__
from .loader import FunnelError, load_funnel, parse_env_file
from .report import describe_flow, describe_products
from .scaffold import create_project, service_unit

DEFAULT_FUNNEL = "funnel.yaml"


def out(text: str = "") -> None:
    print(text, flush=True)


def resolve(args: argparse.Namespace) -> Path:
    return Path(args.funnel).expanduser().resolve()


def env_for(funnel: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    env_file = funnel.parent / ".env"
    if env_file.is_file():
        values.update(parse_env_file(env_file))
    values.update({k: v for k, v in os.environ.items() if v})
    return values


def db_path(args: argparse.Namespace, funnel: Path) -> Path:
    return Path(args.db).expanduser().resolve() if getattr(args, "db", None) else funnel.parent / "funnelbot.db"


def load_or_explain(funnel: Path):
    try:
        return load_funnel(funnel, env_for(funnel))
    except FunnelError as exc:
        out(f"The funnel file has problems ({funnel.name}):")
        out(str(exc))
        out("\nFix them and run `funnelbot validate` again.")
        return None


def ask(question: str, default: str = "") -> str:
    if not sys.stdin.isatty():
        return default
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{question}{suffix}: ").strip()
    except EOFError:
        return default
    return answer or default


def cmd_init(args: argparse.Namespace) -> int:
    folder = Path(args.folder).expanduser().resolve()
    token = args.token or ask("1/3  Bot token from @BotFather (Enter to fill in later)")
    admin = args.admin or ask("2/3  Your Telegram user id (Enter to claim the bot with a link instead)")
    manager = args.manager or ask("3/3  Manager chat id for orders (Enter to skip; you can add it later)")
    try:
        created = create_project(folder, args.lang, token, admin, manager, args.sample)
    except FileExistsError as exc:
        out(str(exc))
        return 1
    if not admin:
        code = secrets.token_urlsafe(9)
        env = folder / ".env"
        env.write_text(env.read_text(encoding="utf-8") + f"CLAIM_CODE={code}\n", encoding="utf-8")
    out(f"Created in {folder}:")
    for name in created:
        out(f"  {name}")
    out("\nNext steps:")
    step = 1
    if not token:
        out(f"  {step}. Get a token: open @BotFather in Telegram, send /newbot, and paste the token into .env (BOT_TOKEN=...)")
        step += 1
    out(f"  {step}. Start the bot:   funnelbot run")
    if not admin:
        out("     The first start prints a one-tap link that makes you the administrator.")
    step += 1
    out(f"  {step}. In Telegram send /admin to your bot and press \"Build the funnel\": steps, buttons, products and")
    out("     access to a private channel are all created with buttons, no file editing needed.")
    out("  Optional: try a demo funnel in this console with `funnelbot init demo --sample` and `funnelbot preview -f demo/funnel.yaml`.")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    funnel_path = resolve(args)
    funnel = load_or_explain(funnel_path)
    if funnel is None:
        return 1
    methods = ", ".join(funnel.payments.configured()) or "none"
    out(f"OK  {funnel_path.name}: {len(funnel.steps)} steps, {len(funnel.products)} products, payment methods: {methods}")
    out("\nSteps (where each one can lead):")
    for line in describe_flow(funnel):
        out(line)
    out("\nProducts:")
    for line in describe_products(funnel):
        out(line)
    if funnel.warnings:
        out("\nWarnings (not errors, but worth a look):")
        for warning in funnel.warnings:
            out(f"  ! {warning}")
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    from .preview import run_preview

    funnel = load_or_explain(resolve(args))
    if funnel is None:
        return 1
    try:
        asyncio.run(run_preview(funnel))
    except KeyboardInterrupt:
        out()
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from .doctor import FAIL, OK, diagnose

    funnel_path = resolve(args)
    funnel = load_or_explain(funnel_path)
    if funnel is None:
        return 1
    token = env_for(funnel_path).get("BOT_TOKEN", "")
    findings = asyncio.run(diagnose(funnel, token))
    marks = {OK: "✓", FAIL: "✗"}
    for level, subject, message in findings:
        out(f"  {marks.get(level, '!')} {subject}: {message}")
    failed = any(level == FAIL for level, _, _ in findings)
    out("\nSomething needs fixing." if failed else "\nEverything that can be checked from here looks fine.")
    return 1 if failed else 0


def cmd_run(args: argparse.Namespace) -> int:
    from .bot import run_bot

    funnel_path = resolve(args)
    funnel = load_or_explain(funnel_path)
    if funnel is None:
        return 1
    env = env_for(funnel_path)
    token = env.get("BOT_TOKEN", "")
    if not token:
        out("BOT_TOKEN is empty. Create a bot in @BotFather (send /newbot) and put the token into the .env file:")
        out("  BOT_TOKEN=123456:ABC...")
        return 1
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(run_bot(funnel_path, db_path(args, funnel_path), token, claim_code=env.get("CLAIM_CODE", "")))
    except KeyboardInterrupt:
        out("Stopped.")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from .report import leads_csv
    from .store import Store

    funnel_path = resolve(args)
    path = db_path(args, funnel_path)
    if not path.is_file():
        out(f"No database at {path}: the bot has not run yet.")
        return 1
    target = Path(args.output)
    target.write_bytes(leads_csv(Store(path)))
    out(f"Saved {target}")
    return 0


def install_unit(funnel_path: Path, db: Optional[Path], user: str, print_only: bool) -> bool:
    unit = service_unit(sys.executable, funnel_path, db, user)
    target = Path("/etc/systemd/system/funnelbot.service")
    is_root = sys.platform.startswith("linux") and os.geteuid() == 0
    if print_only or not is_root:
        out(unit)
        out(f"Save this as {target}, then run:")
        out("  systemctl daemon-reload && systemctl enable --now funnelbot")
        if sys.platform.startswith("linux") and not is_root:
            out("(or run this command again as root and it will do it for you)")
        return False
    target.write_text(unit, encoding="utf-8")
    if os.system("systemctl daemon-reload && systemctl enable --now funnelbot") != 0:
        out("systemctl failed, see the message above.")
        return False
    out("Installed and started. Watch the log with:  journalctl -u funnelbot -f")
    return True


def cmd_install_service(args: argparse.Namespace) -> int:
    funnel_path = resolve(args)
    if load_or_explain(funnel_path) is None:
        return 1
    db = db_path(args, funnel_path) if args.db else None
    started = install_unit(funnel_path, db, args.user or "", args.print)
    if started:
        out("Send /admin to your bot to open the control panel.")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    from .doctor import bot_username
    from .wizard import default_folder, run_setup

    folder = Path(args.folder).expanduser().resolve() if args.folder else default_folder()
    can_service = sys.platform.startswith("linux") and os.geteuid() == 0

    def check(token: str) -> str:
        return asyncio.run(bot_username(token))

    def install(funnel_path: Path) -> bool:
        if args.user:
            os.system(f"chown -R {args.user} {folder}")
        return install_unit(funnel_path, None, args.user or "", False)

    return run_setup(folder, ask, out, check, install, can_service)


def cmd_link(args: argparse.Namespace) -> int:
    from .doctor import bot_username
    from .wizard import claim_link

    funnel_path = resolve(args)
    env = env_for(funnel_path)
    token = env.get("BOT_TOKEN", "")
    if not token:
        out("BOT_TOKEN is empty in .env")
        return 1
    try:
        username = asyncio.run(bot_username(token))
    except ValueError as exc:
        out(f"Telegram did not accept the token: {exc}")
        return 1
    out(f"Your bot:  https://t.me/{username}")
    if env.get("CLAIM_CODE") and not env.get("ADMIN_ID"):
        out("Become the administrator (works until someone claims the bot):")
        out(f"  {claim_link(username, env['CLAIM_CODE'])}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="funnelbot",
        description="A self-hosted Telegram sales-funnel bot: steps, payments and access, described in one YAML file.")
    parser.add_argument("--version", action="version", version=f"funnelbot {__version__}")
    sub = parser.add_subparsers(dest="command")

    def common(p: argparse.ArgumentParser, db: bool = False) -> None:
        p.add_argument("-f", "--funnel", default=DEFAULT_FUNNEL, help=f"funnel file (default: {DEFAULT_FUNNEL})")
        if db:
            p.add_argument("--db", help="database file (default: funnelbot.db next to the funnel file)")

    init = sub.add_parser("init", help="create funnel.yaml, .env and a sample file in a folder")
    init.add_argument("folder", nargs="?", default=".")
    init.add_argument("--lang", choices=("en", "ru"), default="ru", help="language of the template and the bot")
    init.add_argument("--token", default="")
    init.add_argument("--admin", default="")
    init.add_argument("--manager", default="")
    init.add_argument("--sample", action="store_true", help="start from a complete demo funnel instead of an empty one")
    init.set_defaults(func=cmd_init)

    validate = sub.add_parser("validate", help="check the funnel file and show how the steps connect")
    common(validate)
    validate.set_defaults(func=cmd_validate)

    preview = sub.add_parser("preview", help="talk to your funnel in the console, with fake payments and time travel")
    common(preview)
    preview.set_defaults(func=cmd_preview)

    doctor = sub.add_parser("doctor", help="check the token, channel rights and payment credentials")
    common(doctor)
    doctor.set_defaults(func=cmd_doctor)

    run = sub.add_parser("run", help="start the bot")
    common(run, db=True)
    run.set_defaults(func=cmd_run)

    export = sub.add_parser("export", help="save all leads to a CSV file")
    common(export, db=True)
    export.add_argument("output", nargs="?", default="leads.csv")
    export.set_defaults(func=cmd_export)

    setup = sub.add_parser("setup", help="guided setup: token, language, admin, background service")
    setup.add_argument("folder", nargs="?", default="")
    setup.add_argument("--user", help="system user to run the service as")
    setup.set_defaults(func=cmd_setup)

    link = sub.add_parser("link", help="print the bot link and the one-tap link that makes you the administrator")
    common(link)
    link.set_defaults(func=cmd_link)

    service = sub.add_parser("install-service", help="run the bot in the background and start it on boot (Linux, systemd)")
    common(service, db=True)
    service.add_argument("--user", help="system user to run as (default: the current one)")
    service.add_argument("--print", action="store_true", help="only print the unit file")
    service.set_defaults(func=cmd_install_service)
    return parser


def harden_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            continue


def main(argv: Optional[List[str]] = None) -> int:
    harden_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        out("\nNew here? Run:  funnelbot init")
        return 0
    return int(args.func(args))
