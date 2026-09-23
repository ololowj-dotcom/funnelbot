from __future__ import annotations

import asyncio
import html
import json
import re
import time
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Sequence, Set

from .owner import EN as OWNER_EN
from .owner import TABLES as OWNER_TABLES
from .providers import Provider
from .schema import Ask, Button, Funnel
from .store import Store
from .texts import Texts
from .transport import Blocked, Btn, Keyboard, RetryAfter, Transport, TransportError

CURRENCY_MARKS = {"XTR": "⭐", "RUB": "₽", "USD": "$", "EUR": "€"}
PREFIX_MARKS = {"USD": "$", "EUR": "€"}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
DAY = 86400
MAX_HISTORY = 20
MAX_CHAIN = 10


class Values(dict):
    def __missing__(self, key: str) -> str:
        return ""


def format_amount(amount: Decimal, currency: str) -> str:
    value = str(int(amount)) if amount == amount.to_integral_value() else f"{amount:.2f}"
    if currency in PREFIX_MARKS:
        return f"{PREFIX_MARKS[currency]}{value}"
    mark = CURRENCY_MARKS.get(currency)
    return f"{value} {mark}" if mark else f"{value} {currency}"


def format_date(ts: int) -> str:
    return time.strftime("%d.%m.%Y", time.gmtime(ts))


def normalize_answer(ask: Ask, text: str) -> Optional[str]:
    value = text.strip()
    if not value or len(value) > 500:
        return None
    if ask.kind == "email":
        return value.lower() if EMAIL.match(value) else None
    if ask.kind == "phone":
        digits = re.sub(r"[\s\-()]", "", value)
        if re.fullmatch(r"\+?\d{10,15}", digits):
            return digits if digits.startswith("+") else "+" + digits
        return None
    if ask.kind == "number":
        try:
            number = Decimal(value.replace(",", "."))
        except ArithmeticError:
            return None
        return format(number.normalize(), "f") if number.is_finite() else None
    if ask.kind == "choice":
        for choice in ask.choices:
            if choice.strip().lower() == value.lower():
                return choice
        return None
    if ask.kind == "regex":
        return value if ask.regex and re.fullmatch(ask.regex, value) else None
    return value


class Core:
    def __init__(
        self,
        funnel: Funnel,
        store: Store,
        transport: Transport,
        providers: Optional[Dict[str, Provider]] = None,
        clock: Optional[Callable[[], float]] = None,
        funnel_path: Optional[str] = None,
        log: Optional[Callable[[str], None]] = None,
        claim_code: str = "",
    ):
        self.funnel = funnel
        self.store = store
        self.transport = transport
        self.providers = providers or {}
        self.clock = clock or time.time
        self.funnel_path = funnel_path
        self.claim_code = claim_code
        self.log = log or (lambda message: None)
        self.t = Texts(funnel.bot.language, funnel.bot.texts)
        self.alerted: Dict[str, int] = {}
        self.retry_at: Dict[int, int] = {}
        self.last_poll = 0
        self.delivering: Set[int] = set()
        self.answered: Set[str] = set()
        self.tasks: List[asyncio.Task[Any]] = []

    def now(self) -> int:
        return int(self.clock())

    @property
    def html(self) -> bool:
        return self.funnel.bot.parse_mode == "html"

    @property
    def parse_mode(self) -> Optional[str]:
        return "HTML" if self.html else None

    def esc(self, value: Any) -> str:
        text = str(value)
        return html.escape(text, quote=False) if self.html else text

    def claimed_admins(self) -> List[int]:
        raw = self.store.kv_get("admins")
        return [int(x) for x in json.loads(raw)] if raw else []

    def all_admins(self) -> List[int]:
        return list(dict.fromkeys([*self.funnel.bot.admins, *self.claimed_admins()]))

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.funnel.bot.admins or user_id in self.claimed_admins()

    def is_manager_side(self, inc: Any) -> bool:
        return self.is_admin(inc.user_id) or inc.chat_id == self.funnel.bot.manager_chat

    def user_values(self, user: Optional[Dict[str, Any]], **extra: Any) -> Values:
        values = Values()
        if user:
            for key, value in (user.get("answers") or {}).items():
                values[key] = self.esc(value)
            values["first_name"] = self.esc(user.get("first_name") or "")
            values["username"] = self.esc(user.get("username") or "")
            values["id"] = str(user["id"])
        for key, value in extra.items():
            values[key] = self.esc(value)
        return values

    def fmt(self, text: str, user: Optional[Dict[str, Any]], **extra: Any) -> str:
        try:
            return text.format_map(self.user_values(user, **extra))
        except (ValueError, IndexError, KeyError, AttributeError):
            return text

    def tx(self, key: str, raw: Sequence[str] = (), **values: Any) -> str:
        prepared = {k: (v if k in raw else self.esc(v)) for k, v in values.items()}
        text = self.t(key, **prepared)
        return text if self.html else re.sub(r"</?b>", "", text)

    def o(self, key: str, **values: Any) -> str:
        table = OWNER_TABLES.get(self.funnel.bot.language, OWNER_EN)
        return (table.get(key) or OWNER_EN[key]).format(**values)

    def owner_keys(self) -> Set[str]:
        return set(OWNER_EN)

    def button(self, b: Button) -> Btn:
        style = b.style or (self.funnel.bot.pay_style if b.pay else None)
        if b.goto:
            return Btn(b.text, data=f"g:{b.goto}", style=style, icon=b.icon)
        if b.url:
            return Btn(b.text, url=b.url, style=style, icon=b.icon)
        if b.pay:
            return Btn(b.text, data=f"p:{b.pay}", style=style, icon=b.icon)
        if b.copy:
            return Btn(b.text, copy=b.copy, style=style, icon=b.icon)
        if b.back:
            return Btn(b.text, data="b", style=style, icon=b.icon)
        if b.home:
            return Btn(b.text, data="h", style=style, icon=b.icon)
        return Btn(b.text, data="mg", style=style, icon=b.icon)

    def keyboard(self, rows: List[List[Button]]) -> Keyboard:
        return [[self.button(b) for b in row] for row in rows]

    async def send(self, chat_id: int, text: str, keyboard: Optional[Keyboard] = None,
                   image: Optional[str] = None, user_id: Optional[int] = None) -> Optional[int]:
        for attempt in range(2):
            try:
                return await self.transport.send(chat_id, text, keyboard, image, self.parse_mode)
            except Blocked:
                self.store.update_user(user_id if user_id is not None else chat_id, blocked=1)
                return None
            except RetryAfter as exc:
                if attempt:
                    raise
                await asyncio.sleep(min(exc.seconds, 30))
        return None

    async def alert(self, key: str, text: str) -> None:
        now = self.now()
        if now - self.alerted.get(key, 0) < 3600:
            return
        self.alerted[key] = now
        self.log(f"ALERT {text}")
        targets = [self.funnel.bot.manager_chat] if self.funnel.bot.manager_chat is not None else self.all_admins()
        for chat in targets:
            try:
                await self.transport.send(chat, "⚠️ " + html.escape(text, quote=False), None, None, "HTML")
            except TransportError as exc:
                self.log(f"alert to {chat} failed: {exc}")

    def owned_all(self, user_id: int, products: List[str]) -> bool:
        if not products:
            return False
        owned = set(self.store.owned_products(user_id))
        return all(p in owned for p in products)

    def apply_funnel(self, funnel: Funnel) -> None:
        self.funnel = funnel
        self.t = Texts(funnel.bot.language, funnel.bot.texts)
