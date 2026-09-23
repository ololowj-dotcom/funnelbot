from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

STEP_ID = re.compile(r"^[a-z0-9_]{1,40}$")
PRODUCT_ID = re.compile(r"^[a-z0-9_]{1,30}$")
ANSWER_KEY = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
DURATION = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.I)
ASK_KINDS = ("text", "email", "phone", "number", "choice", "regex")
METHODS = ("stars", "telegram", "yookassa", "crypto", "manual")
LANGUAGES = ("en", "ru")
PARSE_MODES = ("html", "none")
STYLES = ("primary", "success", "danger")
USER_FIELDS = ("first_name", "username", "id")
ACCESS_FIELDS = ("product",)
STARS = "XTR"


def parse_duration(value: object) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value * 60 if value > 0 else None
    if not isinstance(value, str):
        return None
    match = DURATION.match(value)
    if not match:
        return None
    seconds = int(match.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2).lower()]
    return seconds if seconds > 0 else None


@dataclass
class Button:
    text: str
    goto: Optional[str] = None
    url: Optional[str] = None
    pay: Optional[str] = None
    back: bool = False
    home: bool = False
    manager: bool = False
    copy: Optional[str] = None
    style: Optional[str] = None
    icon: Optional[str] = None


@dataclass
class Ask:
    key: str
    kind: str = "text"
    choices: List[str] = field(default_factory=list)
    regex: Optional[str] = None
    error: str = ""


@dataclass
class Nudge:
    after: int
    text: str
    image: Optional[str] = None
    buttons: List[List[Button]] = field(default_factory=list)


@dataclass
class Step:
    id: str
    text: str
    image: Optional[str] = None
    buttons: List[List[Button]] = field(default_factory=list)
    next: Optional[str] = None
    ask: Optional[Ask] = None
    pay: Optional[str] = None
    paid: Optional[str] = None
    wait: int = 0
    nudges: List[Nudge] = field(default_factory=list)
    end: bool = False


@dataclass
class Access:
    kind: str
    chat: Optional[int] = None
    days: Optional[int] = None
    remind: List[int] = field(default_factory=list)
    text: str = ""
    files: List[str] = field(default_factory=list)


@dataclass
class Product:
    id: str
    title: str
    description: str
    prices: Dict[str, Decimal]
    access: List[Access] = field(default_factory=list)
    image: Optional[str] = None


@dataclass
class Stars:
    pass


@dataclass
class TelegramPay:
    provider_token: str
    currency: str = "RUB"
    need_email: bool = False
    receipt: Optional[Receipt] = None


@dataclass
class Receipt:
    vat_code: int = 1
    tax_system_code: Optional[int] = None
    payment_subject: str = "service"
    payment_mode: str = "full_payment"
    contact_key: str = "email"


@dataclass
class YooKassa:
    shop_id: str
    secret_key: str
    return_url: str
    currency: str = "RUB"
    api_base: str = "https://api.yookassa.ru/v3"
    receipt: Optional[Receipt] = None


@dataclass
class Crypto:
    token: str
    asset: str = "USDT"
    api_base: str = "https://pay.crypt.bot/api"
    expires_in: int = 3600


@dataclass
class Manual:
    text: str
    currency: str = "RUB"


@dataclass
class Payments:
    stars: Optional[Stars] = None
    telegram: Optional[TelegramPay] = None
    yookassa: Optional[YooKassa] = None
    crypto: Optional[Crypto] = None
    manual: Optional[Manual] = None
    poll_seconds: int = 20
    pending_ttl: int = 86400

    def currency_of(self, method: str) -> Optional[str]:
        if method == "stars" and self.stars is not None:
            return STARS
        if method == "telegram" and self.telegram:
            return self.telegram.currency
        if method == "yookassa" and self.yookassa:
            return self.yookassa.currency
        if method == "crypto" and self.crypto:
            return self.crypto.asset
        if method == "manual" and self.manual:
            return self.manual.currency
        return None

    def configured(self) -> List[str]:
        return [m for m in METHODS if self.currency_of(m)]


@dataclass
class Document:
    title: str
    url: str


@dataclass
class Consent:
    text: str
    documents: List[Document] = field(default_factory=list)
    agree: str = ""


@dataclass
class BotCfg:
    language: str = "ru"
    admins: List[int] = field(default_factory=list)
    manager_chat: Optional[int] = None
    parse_mode: str = "html"
    enforce_expiry: bool = True
    test_mode: bool = False
    pay_style: Optional[str] = "success"
    texts: Dict[str, str] = field(default_factory=dict)


@dataclass
class Funnel:
    bot: BotCfg
    payments: Payments
    products: Dict[str, Product]
    steps: Dict[str, Step]
    start: str
    consent: Optional[Consent] = None
    base_dir: Path = Path(".")
    warnings: List[str] = field(default_factory=list)

    def methods_for(self, product_id: str) -> List[str]:
        product = self.products[product_id]
        methods: List[str] = []
        for method in self.payments.configured():
            if self.payments.currency_of(method) in product.prices:
                methods.append(method)
        return methods

    def answer_keys(self) -> List[str]:
        return sorted({s.ask.key for s in self.steps.values() if s.ask})
