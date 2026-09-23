from __future__ import annotations

import difflib
import os
import re
import string
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

from .schema import (
    ACCESS_FIELDS,
    ANSWER_KEY,
    ASK_KINDS,
    LANGUAGES,
    PARSE_MODES,
    PRODUCT_ID,
    STARS,
    STEP_ID,
    STYLES,
    USER_FIELDS,
    Access,
    Ask,
    BotCfg,
    Button,
    Consent,
    Crypto,
    Document,
    Funnel,
    Manual,
    Nudge,
    Payments,
    Product,
    Receipt,
    Stars,
    Step,
    TelegramPay,
    YooKassa,
    parse_duration,
)
from .texts import KEYS as TEXT_KEYS

ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
CALLBACK_LIMIT = 60
BUTTON_ACTIONS = ("goto", "url", "pay", "back", "home", "manager", "copy")
MAX_BUTTONS_PER_ROW = 8
MAX_BUTTONS = 100
DIGITAL_ACCESS = ("channel", "message")


class FunnelError(Exception):
    pass


class Problems:
    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"{where}: {message}")


def parse_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def interpolate(value: Any, env: Dict[str, str], where: str, problems: Problems) -> Any:
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            if env.get(name):
                return env[name]
            if default is not None:
                return default
            problems.error(where, f"environment variable {name} is not set (put it in the .env file next to the funnel file)")
            return ""

        return ENV_RE.sub(replace, value)
    if isinstance(value, dict):
        return {k: interpolate(v, env, f"{where}.{k}" if where else str(k), problems) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(v, env, f"{where}[{i}]", problems) for i, v in enumerate(value)]
    return value


def check_keys(table: Dict[str, Any], where: str, allowed: List[str], problems: Problems) -> None:
    for key in table:
        if key not in allowed:
            hint = difflib.get_close_matches(str(key), allowed, n=1)
            more = f" (did you mean '{hint[0]}'?)" if hint else f" (allowed: {', '.join(allowed)})"
            problems.error(f"{where}.{key}" if where else str(key), f"unknown setting{more}")


def as_table(value: Any, where: str, problems: Problems) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        problems.error(where, "must be a mapping (key: value)")
        return {}
    return value


def as_int(value: Any, where: str, problems: Problems, minimum: Optional[int] = None) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
            value = int(value.strip())
        else:
            problems.error(where, "must be a whole number")
            return None
    if minimum is not None and value < minimum:
        problems.error(where, f"must be >= {minimum}")
        return None
    return value


def as_text(value: Any, where: str, problems: Problems, required: bool = False) -> str:
    if value is None:
        if required:
            problems.error(where, "is required")
        return ""
    if not isinstance(value, str):
        problems.error(where, "must be text")
        return ""
    if required and not value.strip():
        problems.error(where, "must not be empty")
    return value


def as_bool(value: Any, where: str, problems: Problems, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        problems.error(where, "must be true or false")
        return default
    return value


def placeholders(text: str) -> List[str]:
    names: List[str] = []
    for _, field_name, _, _ in string.Formatter().parse(text):
        if field_name is not None:
            names.append(field_name.split(".")[0].split("[")[0])
    return names


def check_text(text: str, where: str, allowed: Set[str], problems: Problems) -> None:
    try:
        names = placeholders(text)
    except ValueError as exc:
        problems.error(where, f"broken {{placeholder}}: {exc}")
        return
    for name in sorted(set(names)):
        if name not in allowed:
            problems.error(where, f"unknown placeholder {{{name}}}; available: " + ", ".join("{" + a + "}" for a in sorted(allowed)))


def check_media(value: Any, where: str, base: Path, problems: Problems) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        problems.error(where, "must be a file path, an http(s) link or file_id:<telegram file id>")
        return None
    if value.startswith(("http://", "https://", "file_id:")):
        return value
    path = Path(value)
    resolved = path if path.is_absolute() else base / path
    if not resolved.is_file():
        problems.error(where, f"file not found: {value} (paths are relative to the funnel file)")
        return None
    return str(resolved)


def parse_style(value: Any, where: str, problems: Problems) -> Optional[str]:
    if value is None:
        return None
    if value not in STYLES:
        problems.error(where, f"must be one of: {', '.join(STYLES)} (primary = blue, success = green, danger = red)")
        return None
    return value


def parse_buttons(raw: Any, where: str, problems: Problems) -> List[List[Button]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        problems.error(where, "must be a list of buttons or a list of rows")
        return []
    rows: List[List[Button]] = []
    total = 0
    for r, row in enumerate(raw):
        items = row if isinstance(row, list) else [row]
        if len(items) > MAX_BUTTONS_PER_ROW:
            problems.error(f"{where}[{r}]", f"a row can hold at most {MAX_BUTTONS_PER_ROW} buttons")
        parsed: List[Button] = []
        for b, item in enumerate(items):
            spot = f"{where}[{r}][{b}]" if isinstance(row, list) else f"{where}[{r}]"
            table = as_table(item, spot, problems)
            check_keys(table, spot, ["text", *BUTTON_ACTIONS, "style", "icon"], problems)
            text = as_text(table.get("text"), f"{spot}.text", problems, required=True)
            actions = [k for k in BUTTON_ACTIONS if table.get(k)]
            if len(actions) != 1:
                problems.error(spot, f"a button needs exactly one of: {', '.join(BUTTON_ACTIONS)}")
                continue
            action = actions[0]
            value = table[action]
            if action in ("back", "home", "manager") and value is not True:
                problems.error(f"{spot}.{action}", "must be true")
                continue
            if action in ("goto", "url", "pay", "copy") and not isinstance(value, str):
                problems.error(f"{spot}.{action}", "must be text")
                continue
            if action == "copy" and len(value) > 256:
                problems.error(f"{spot}.copy", "can hold at most 256 characters")
            icon = table.get("icon")
            if icon is not None and not (isinstance(icon, (str, int)) and re.fullmatch(r"\d{5,25}", str(icon))):
                problems.error(f"{spot}.icon", "must be a custom emoji id (a long number)")
                icon = None
            parsed.append(Button(
                text=text,
                goto=value if action == "goto" else None,
                url=value if action == "url" else None,
                pay=value if action == "pay" else None,
                back=action == "back",
                home=action == "home",
                manager=action == "manager",
                copy=value if action == "copy" else None,
                style=parse_style(table.get("style"), f"{spot}.style", problems),
                icon=str(icon) if icon is not None else None,
            ))
        total += len(parsed)
        if parsed:
            rows.append(parsed)
    if total > MAX_BUTTONS:
        problems.error(where, f"at most {MAX_BUTTONS} buttons fit in one message")
    return rows


def parse_bot(raw: Any, problems: Problems) -> BotCfg:
    table = as_table(raw, "bot", problems)
    check_keys(table, "bot", ["language", "admins", "manager_chat", "parse_mode", "enforce_expiry", "test_mode", "pay_style", "texts"], problems)
    cfg = BotCfg()
    language = table.get("language", "ru")
    if language not in LANGUAGES:
        problems.error("bot.language", f"must be one of: {', '.join(LANGUAGES)}")
    else:
        cfg.language = language
    mode = table.get("parse_mode", "html")
    if mode not in PARSE_MODES:
        problems.error("bot.parse_mode", f"must be one of: {', '.join(PARSE_MODES)}")
    else:
        cfg.parse_mode = mode
    admins = table.get("admins", [])
    if not isinstance(admins, list):
        problems.error("bot.admins", "must be a list of Telegram user ids")
        admins = []
    for i, admin in enumerate(admins):
        if admin in ("", None):
            continue
        value = as_int(admin, f"bot.admins[{i}]", problems)
        if value is not None:
            cfg.admins.append(value)
    if table.get("manager_chat") not in (None, ""):
        cfg.manager_chat = as_int(table["manager_chat"], "bot.manager_chat", problems)
    cfg.enforce_expiry = as_bool(table.get("enforce_expiry"), "bot.enforce_expiry", problems, True)
    cfg.test_mode = as_bool(table.get("test_mode"), "bot.test_mode", problems, False)
    if "pay_style" in table:
        raw_style = table["pay_style"]
        plain = raw_style is None or str(raw_style).lower() in ("", "none", "null", "false")
        cfg.pay_style = None if plain else parse_style(raw_style, "bot.pay_style", problems)
    texts = as_table(table.get("texts"), "bot.texts", problems)
    for key, value in texts.items():
        if key not in TEXT_KEYS:
            hint = difflib.get_close_matches(str(key), list(TEXT_KEYS), n=1)
            more = f" (did you mean '{hint[0]}'?)" if hint else ""
            problems.error(f"bot.texts.{key}", f"unknown built-in phrase{more}")
        elif not isinstance(value, str):
            problems.error(f"bot.texts.{key}", "must be text")
        else:
            cfg.texts[key] = value
    return cfg


def parse_receipt(raw: Any, where: str, problems: Problems) -> Optional[Receipt]:
    if raw is None:
        return None
    r = as_table(raw, where, problems)
    check_keys(r, where, ["vat_code", "tax_system_code", "payment_subject", "payment_mode", "contact_key"], problems)
    tax = None
    if r.get("tax_system_code") is not None:
        tax = as_int(r["tax_system_code"], f"{where}.tax_system_code", problems, 1)
    return Receipt(
        vat_code=as_int(r.get("vat_code", 1), f"{where}.vat_code", problems, 1) or 1,
        tax_system_code=tax,
        payment_subject=str(r.get("payment_subject", "service")),
        payment_mode=str(r.get("payment_mode", "full_payment")),
        contact_key=str(r.get("contact_key", "email")),
    )


def parse_payments(raw: Any, problems: Problems) -> Payments:
    table = as_table(raw, "payments", problems)
    check_keys(table, "payments", ["stars", "telegram", "yookassa", "crypto", "manual", "poll_seconds", "pending_ttl"], problems)
    pay = Payments()
    if table.get("poll_seconds") is not None:
        pay.poll_seconds = as_int(table["poll_seconds"], "payments.poll_seconds", problems, 5) or pay.poll_seconds
    if table.get("pending_ttl") is not None:
        ttl = parse_duration(table["pending_ttl"])
        if ttl is None:
            problems.error("payments.pending_ttl", "must be a duration such as 2h or 1d")
        else:
            pay.pending_ttl = ttl
    if table.get("stars") not in (None, False):
        pay.stars = Stars()
    tg = table.get("telegram")
    if tg is not None:
        t = as_table(tg, "payments.telegram", problems)
        check_keys(t, "payments.telegram", ["provider_token", "currency", "need_email", "receipt"], problems)
        token = as_text(t.get("provider_token"), "payments.telegram.provider_token", problems, required=True)
        currency = str(t.get("currency", "RUB")).upper()
        if currency == STARS:
            problems.error("payments.telegram.currency", "XTR is Telegram Stars: use `payments: {stars: true}` instead")
        pay.telegram = TelegramPay(
            provider_token=token, currency=currency,
            need_email=as_bool(t.get("need_email"), "payments.telegram.need_email", problems, False),
            receipt=parse_receipt(t.get("receipt"), "payments.telegram.receipt", problems),
        )
    yk = table.get("yookassa")
    if yk is not None:
        y = as_table(yk, "payments.yookassa", problems)
        check_keys(y, "payments.yookassa", ["shop_id", "secret_key", "return_url", "currency", "api_base", "receipt"], problems)
        pay.yookassa = YooKassa(
            shop_id=str(as_text(y.get("shop_id"), "payments.yookassa.shop_id", problems, required=True)),
            secret_key=as_text(y.get("secret_key"), "payments.yookassa.secret_key", problems, required=True),
            return_url=as_text(y.get("return_url"), "payments.yookassa.return_url", problems, required=True),
            currency=str(y.get("currency", "RUB")).upper(),
            api_base=str(y.get("api_base", "https://api.yookassa.ru/v3")).rstrip("/"),
            receipt=parse_receipt(y.get("receipt"), "payments.yookassa.receipt", problems),
        )
    cr = table.get("crypto")
    if cr is not None:
        c = as_table(cr, "payments.crypto", problems)
        check_keys(c, "payments.crypto", ["token", "asset", "api_base", "expires_in"], problems)
        expires = 3600
        if c.get("expires_in") is not None:
            parsed = parse_duration(c["expires_in"])
            if parsed is None:
                problems.error("payments.crypto.expires_in", "must be a duration such as 1h")
            else:
                expires = parsed
        pay.crypto = Crypto(
            token=as_text(c.get("token"), "payments.crypto.token", problems, required=True),
            asset=str(c.get("asset", "USDT")).upper(),
            api_base=str(c.get("api_base", "https://pay.crypt.bot/api")).rstrip("/"),
            expires_in=expires,
        )
    mn = table.get("manual")
    if mn is not None:
        m = as_table(mn, "payments.manual", problems)
        check_keys(m, "payments.manual", ["text", "currency"], problems)
        pay.manual = Manual(
            text=as_text(m.get("text"), "payments.manual.text", problems, required=True),
            currency=str(m.get("currency", "RUB")).upper(),
        )
    return pay


def parse_remind(value: Any, days: Optional[int], where: str, problems: Problems) -> List[int]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    result: List[int] = []
    for i, item in enumerate(items):
        number = as_int(item, f"{where}[{i}]" if isinstance(value, list) else where, problems, 1)
        if number is None:
            continue
        if days is not None and number >= days:
            problems.error(where, "every reminder must be smaller than days")
            continue
        result.append(number)
    return sorted(set(result), reverse=True)


def parse_access(raw: Any, where: str, base: Path, bot: BotCfg, allowed: Set[str], problems: Problems) -> List[Access]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        problems.error(where, "must be a list of things to give after payment")
        return []
    rules: List[Access] = []
    for i, item in enumerate(raw):
        spot = f"{where}[{i}]"
        table = as_table(item, spot, problems)
        check_keys(table, spot, ["channel", "message", "manager"], problems)
        kinds = [k for k in ("channel", "message", "manager") if k in table]
        if len(kinds) != 1:
            problems.error(spot, "each item needs exactly one of: channel, message, manager")
            continue
        kind = kinds[0]
        body = table[kind]
        if kind == "channel":
            t = as_table(body, f"{spot}.channel", problems)
            check_keys(t, f"{spot}.channel", ["chat", "days", "remind_days"], problems)
            chat = as_int(t.get("chat"), f"{spot}.channel.chat", problems) if t.get("chat") is not None else None
            if chat is None:
                problems.error(f"{spot}.channel.chat", "is required: the numeric id of the channel or group (starts with -100)")
            days = as_int(t["days"], f"{spot}.channel.days", problems, 1) if t.get("days") is not None else None
            remind = parse_remind(t.get("remind_days"), days, f"{spot}.channel.remind_days", problems)
            if remind and days is None:
                problems.error(f"{spot}.channel.remind_days", "reminders need `days` (a lifetime access never ends)")
            if chat is not None:
                rules.append(Access(kind="channel", chat=chat, days=days, remind=remind))
        elif kind == "message":
            t = as_table(body, f"{spot}.message", problems)
            check_keys(t, f"{spot}.message", ["text", "file", "files"], problems)
            text = as_text(t.get("text"), f"{spot}.message.text", problems)
            check_text(text, f"{spot}.message.text", allowed | set(ACCESS_FIELDS), problems)
            raw_files = t.get("files", [])
            if t.get("file"):
                raw_files = [t["file"]] + (raw_files if isinstance(raw_files, list) else [])
            if not isinstance(raw_files, list):
                problems.error(f"{spot}.message.files", "must be a list of files")
                raw_files = []
            files = [f for f in (check_media(x, f"{spot}.message.files[{n}]", base, problems) for n, x in enumerate(raw_files)) if f]
            if not text.strip() and not files:
                problems.error(f"{spot}.message", "needs a text or at least one file")
            rules.append(Access(kind="message", text=text, files=files))
        else:
            if bot.manager_chat is None:
                problems.error(f"{spot}.manager", "needs bot.manager_chat (the chat that receives order cards)")
            t = as_table(body, f"{spot}.manager", problems)
            check_keys(t, f"{spot}.manager", ["text"], problems)
            rules.append(Access(kind="manager", text=as_text(t.get("text"), f"{spot}.manager.text", problems)))
    return rules


def parse_products(raw: Any, base: Path, bot: BotCfg, allowed: Set[str], problems: Problems) -> Dict[str, Product]:
    table = as_table(raw, "products", problems)
    products: Dict[str, Product] = {}
    for pid, body in table.items():
        where = f"products.{pid}"
        if not isinstance(pid, str) or not PRODUCT_ID.match(pid):
            problems.error(where, "the product id must be 1-30 characters: lowercase letters, digits, underscore")
            continue
        t = as_table(body, where, problems)
        check_keys(t, where, ["title", "description", "prices", "access", "image"], problems)
        title = as_text(t.get("title"), f"{where}.title", problems, required=True)
        description = as_text(t.get("description"), f"{where}.description", problems)
        prices: Dict[str, Decimal] = {}
        raw_prices = as_table(t.get("prices"), f"{where}.prices", problems)
        if not raw_prices:
            problems.error(f"{where}.prices", "is required, for example {RUB: 4900, XTR: 3000}")
        for currency, amount in raw_prices.items():
            try:
                value = Decimal(str(amount))
            except InvalidOperation:
                problems.error(f"{where}.prices.{currency}", "must be a number")
                continue
            if value <= 0:
                problems.error(f"{where}.prices.{currency}", "must be greater than zero")
                continue
            if str(currency).upper() == STARS and value != value.to_integral_value():
                problems.error(f"{where}.prices.{currency}", "Stars come in whole numbers")
                continue
            prices[str(currency).upper()] = value
        access = parse_access(t.get("access"), f"{where}.access", base, bot, allowed, problems)
        products[pid] = Product(
            id=pid, title=title, description=description, prices=prices, access=access,
            image=check_media(t.get("image"), f"{where}.image", base, problems))
    return products


def parse_ask(raw: Any, where: str, problems: Problems) -> Optional[Ask]:
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = {"key": raw}
    t = as_table(raw, where, problems)
    check_keys(t, where, ["key", "type", "choices", "regex", "error"], problems)
    key = t.get("key")
    if not isinstance(key, str) or not ANSWER_KEY.match(key):
        problems.error(f"{where}.key", "is required: a name starting with a lowercase letter (letters, digits, underscore)")
        return None
    kind = t.get("type", "text")
    if kind not in ASK_KINDS:
        problems.error(f"{where}.type", f"must be one of: {', '.join(ASK_KINDS)}")
        return None
    ask = Ask(key=key, kind=kind, error=as_text(t.get("error"), f"{where}.error", problems))
    if kind == "choice":
        choices = t.get("choices")
        if not isinstance(choices, list) or not choices or not all(isinstance(c, str) and c.strip() for c in choices):
            problems.error(f"{where}.choices", "a choice question needs a list of options")
        else:
            ask.choices = list(choices)
    if kind == "regex":
        pattern = t.get("regex")
        if not isinstance(pattern, str):
            problems.error(f"{where}.regex", "a regex question needs a pattern")
        else:
            try:
                re.compile(pattern)
                ask.regex = pattern
            except re.error as exc:
                problems.error(f"{where}.regex", f"broken pattern: {exc}")
    return ask


def parse_steps(raw: Any, base: Path, allowed: Set[str], problems: Problems) -> Dict[str, Step]:
    table = as_table(raw, "steps", problems)
    steps: Dict[str, Step] = {}
    for sid, body in table.items():
        where = f"steps.{sid}"
        if not isinstance(sid, str) or not STEP_ID.match(sid):
            problems.error(where, "the step id must be 1-40 characters: lowercase letters, digits, underscore")
            continue
        t = as_table(body, where, problems)
        check_keys(t, where, ["text", "image", "buttons", "next", "ask", "pay", "paid", "wait", "nudges", "end"], problems)
        text = as_text(t.get("text"), f"{where}.text", problems, required=True)
        check_text(text, f"{where}.text", allowed, problems)
        step = Step(id=sid, text=text, image=check_media(t.get("image"), f"{where}.image", base, problems))
        step.buttons = parse_buttons(t.get("buttons"), f"{where}.buttons", problems)
        step.next = t.get("next") if isinstance(t.get("next"), str) else None
        if t.get("next") is not None and step.next is None:
            problems.error(f"{where}.next", "must be a step id")
        step.ask = parse_ask(t.get("ask"), f"{where}.ask", problems)
        step.pay = t.get("pay") if isinstance(t.get("pay"), str) else None
        step.paid = t.get("paid") if isinstance(t.get("paid"), str) else None
        step.end = as_bool(t.get("end"), f"{where}.end", problems, False)
        if t.get("wait") is not None:
            seconds = parse_duration(t["wait"])
            if seconds is None:
                problems.error(f"{where}.wait", "must be a duration such as 30s, 10m or 2h")
            else:
                step.wait = seconds
        nudges = t.get("nudges", [])
        if not isinstance(nudges, list):
            problems.error(f"{where}.nudges", "must be a list of reminders")
            nudges = []
        for n, item in enumerate(nudges):
            spot = f"{where}.nudges[{n}]"
            nt = as_table(item, spot, problems)
            check_keys(nt, spot, ["after", "text", "image", "buttons"], problems)
            after = parse_duration(nt.get("after"))
            if after is None:
                problems.error(f"{spot}.after", "is required: a duration such as 30m, 2h or 1d")
                continue
            ntext = as_text(nt.get("text"), f"{spot}.text", problems, required=True)
            check_text(ntext, f"{spot}.text", allowed, problems)
            step.nudges.append(Nudge(
                after=after, text=ntext, image=check_media(nt.get("image"), f"{spot}.image", base, problems),
                buttons=parse_buttons(nt.get("buttons"), f"{spot}.buttons", problems)))
        step.nudges.sort(key=lambda x: x.after)
        if step.ask and not step.next:
            problems.error(where, "a step with `ask` needs `next` (where to go after the answer)")
        if step.ask and (step.pay or step.buttons):
            problems.error(where, "a step with `ask` cannot also have `pay` or `buttons`")
        steps[sid] = step
    return steps


def parse_consent(raw: Any, problems: Problems) -> Optional[Consent]:
    if raw is None:
        return None
    t = as_table(raw, "consent", problems)
    check_keys(t, "consent", ["text", "documents", "agree"], problems)
    consent = Consent(
        text=as_text(t.get("text"), "consent.text", problems, required=True),
        agree=as_text(t.get("agree"), "consent.agree", problems),
    )
    docs = t.get("documents", [])
    if not isinstance(docs, list):
        problems.error("consent.documents", "must be a list of {title, url}")
        docs = []
    for i, item in enumerate(docs):
        d = as_table(item, f"consent.documents[{i}]", problems)
        check_keys(d, f"consent.documents[{i}]", ["title", "url"], problems)
        title = as_text(d.get("title"), f"consent.documents[{i}].title", problems, required=True)
        url = as_text(d.get("url"), f"consent.documents[{i}].url", problems, required=True)
        if url and not url.startswith(("http://", "https://")):
            problems.error(f"consent.documents[{i}].url", "must start with http:// or https://")
        consent.documents.append(Document(title=title, url=url))
    return consent


def all_button_rows(step: Step) -> List[List[List[Button]]]:
    return [step.buttons] + [n.buttons for n in step.nudges]


def reachable(steps: Dict[str, Step], start: str) -> Set[str]:
    seen: Set[str] = set()
    todo = [start]
    while todo:
        sid = todo.pop()
        if sid in seen or sid not in steps:
            continue
        seen.add(sid)
        step = steps[sid]
        for target in (step.next, step.paid):
            if target:
                todo.append(target)
        for rows in all_button_rows(step):
            for row in rows:
                todo += [b.goto for b in row if b.goto]
                if any(b.home for b in row):
                    todo.append(start)
    return seen


def cross_check(funnel: Funnel, problems: Problems) -> None:
    steps, products = funnel.steps, funnel.products
    if not steps:
        problems.error("steps", "at least one step is required")
        return
    if funnel.start not in steps:
        problems.error("start", f"unknown step '{funnel.start}'")

    def suggest(target: str, options: List[str]) -> str:
        hint = difflib.get_close_matches(target, options, n=1)
        return f" (did you mean '{hint[0]}'?)" if hint else ""

    def need_step(target: Optional[str], where: str) -> None:
        if target and target not in steps:
            problems.error(where, f"unknown step '{target}'{suggest(target, list(steps))}")

    def need_product(target: Optional[str], where: str) -> None:
        if target and target not in products:
            problems.error(where, f"unknown product '{target}'{suggest(target, list(products))}")

    def check_button_rows(rows: List[List[Button]], where: str) -> None:
        for r, row in enumerate(rows):
            for b, button in enumerate(row):
                spot = f"{where}[{r}][{b}]"
                need_step(button.goto, f"{spot}.goto")
                need_product(button.pay, f"{spot}.pay")
                if button.goto and len(f"g:{button.goto}") > CALLBACK_LIMIT:
                    problems.error(spot, "the step id is too long for a Telegram button")
                if button.url and not button.url.startswith(("http://", "https://", "tg://")):
                    problems.error(f"{spot}.url", "must start with http://, https:// or tg://")
                if button.manager and funnel.bot.manager_chat is None:
                    problems.error(f"{spot}.manager", "needs bot.manager_chat")

    for sid, step in steps.items():
        where = f"steps.{sid}"
        need_step(step.next, f"{where}.next")
        need_step(step.paid, f"{where}.paid")
        need_product(step.pay, f"{where}.pay")
        check_button_rows(step.buttons, f"{where}.buttons")
        for n, nudge in enumerate(step.nudges):
            check_button_rows(nudge.buttons, f"{where}.nudges[{n}].buttons")
        offers = step.pay or any(b.pay for rows in all_button_rows(step) for row in rows for b in row)
        if step.paid and not offers:
            problems.error(f"{where}.paid", "only makes sense in a step that offers a product (`pay`)")
    for pid, product in products.items():
        if not funnel.methods_for(pid):
            configured = ", ".join(f"{m} ({funnel.payments.currency_of(m)})" for m in funnel.payments.configured()) or "none"
            problems.error(
                f"products.{pid}.prices",
                f"no configured payment method can charge this product (methods: {configured}; "
                f"prices: {', '.join(product.prices) or 'none'}); add a price in one of those currencies",
            )
        digital = any(a.kind in DIGITAL_ACCESS for a in product.access)
        others = [m for m in funnel.methods_for(pid) if m != "stars"]
        if digital and others:
            problems.warn(
                f"products.{pid}",
                f"gives digital access but can be paid with {', '.join(others)}: Telegram's Bot Developer Terms (6.2) "
                "require Telegram Stars for digital goods and services; other methods are at your own risk "
                "(physical goods and real-world services are fine)")

    used = {s.pay for s in steps.values() if s.pay}
    for step in steps.values():
        for rows in all_button_rows(step):
            for row in rows:
                used |= {b.pay for b in row if b.pay}
    for pid in products:
        if pid not in used:
            problems.warn(f"products.{pid}", "is not offered in any step (no `pay:` uses it)")
    for method in funnel.payments.configured():
        currency = funnel.payments.currency_of(method)
        if products and not any(currency in p.prices for p in products.values()):
            problems.warn(f"payments.{method}", f"is configured but no product has a price in {currency}")
    if funnel.payments.manual and funnel.bot.manager_chat is None:
        problems.error("payments.manual", "needs bot.manager_chat: the chat where payment screenshots are reviewed")
    if funnel.start in steps:
        seen = reachable(steps, funnel.start)
        for sid in steps:
            if sid not in seen:
                problems.warn(f"steps.{sid}", "cannot be reached from the start step")
    for sid, step in steps.items():
        if not (step.next or step.buttons or step.pay or step.end or step.ask):
            problems.warn(f"steps.{sid}", "is a dead end: no next, buttons, pay or `end: true`")
    keys = funnel.answer_keys()
    tg = funnel.payments.telegram
    if tg and tg.receipt and not tg.need_email and tg.receipt.contact_key not in keys:
        problems.error("payments.telegram.receipt", f"needs a customer contact: set need_email: true or add an `ask` step for '{tg.receipt.contact_key}'")
    yk = funnel.payments.yookassa
    if yk and yk.receipt and yk.receipt.contact_key not in keys:
        problems.error("payments.yookassa.receipt.contact_key",
                       f"the funnel never asks for '{yk.receipt.contact_key}'; add an `ask` step that collects it (email or phone)")
    if funnel.bot.test_mode and not funnel.bot.admins:
        problems.warn("bot.test_mode", "is on but bot.admins is empty: nobody can use the test payment")


def parse_funnel(data: Any, env: Dict[str, str], base: Path) -> Funnel:
    problems = Problems()
    if not isinstance(data, dict):
        raise FunnelError("the funnel file must be a mapping with steps, products, payments, bot and start")
    data = interpolate(data, env, "", problems)
    check_keys(data, "", ["bot", "payments", "products", "steps", "start", "consent"], problems)
    bot = parse_bot(data.get("bot"), problems)
    payments = parse_payments(data.get("payments"), problems)
    raw_steps = as_table(data.get("steps"), "steps", problems)
    ask_keys: Set[str] = set()
    for body in raw_steps.values():
        if isinstance(body, dict):
            ask = body.get("ask")
            key = ask.get("key") if isinstance(ask, dict) else ask if isinstance(ask, str) else None
            if isinstance(key, str):
                ask_keys.add(key)
    allowed = set(USER_FIELDS) | ask_keys
    products = parse_products(data.get("products"), base, bot, allowed, problems)
    steps = parse_steps(data.get("steps"), base, allowed, problems)
    consent = parse_consent(data.get("consent"), problems)
    start = data.get("start")
    if not isinstance(start, str):
        start = next(iter(steps), "")
        if not problems.errors:
            problems.warn("start", f"not set; using the first step '{start}'")
    funnel = Funnel(bot=bot, payments=payments, products=products, steps=steps, start=start, consent=consent, base_dir=base)
    cross_check(funnel, problems)
    funnel.warnings = problems.warnings
    if problems.errors:
        raise FunnelError("\n".join(f"  - {e}" for e in problems.errors))
    return funnel


def load_funnel(path: Path, env: Optional[Dict[str, str]] = None) -> Funnel:
    path = Path(path)
    if not path.is_file():
        raise FunnelError(f"funnel file not found: {path}  (create one with `funnelbot init`)")
    merged: Dict[str, str] = {}
    env_file = path.parent / ".env"
    if env_file.is_file():
        merged.update(parse_env_file(env_file))
    merged.update(os.environ if env is None else env)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise FunnelError(f"{path.name} is not valid YAML: {exc}") from exc
    return parse_funnel(data, merged, path.parent.resolve())
