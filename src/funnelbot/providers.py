from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional

import aiohttp

from .schema import Crypto, Receipt, YooKassa

TIMEOUT = aiohttp.ClientTimeout(total=25)


class ProviderError(Exception):
    pass


@dataclass
class Created:
    external_id: str
    url: str


def money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class Provider:
    async def create(self, payment_id: int, amount: Decimal, description: str, contact: Dict[str, str]) -> Created:
        raise NotImplementedError

    async def status(self, external_id: str) -> str:
        raise NotImplementedError

    async def check(self) -> str:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class Http:
    def __init__(self) -> None:
        self.session: Optional[aiohttp.ClientSession] = None

    async def request(self, method: str, url: str, **kwargs: Any) -> Any:
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=TIMEOUT)
        try:
            async with self.session.request(method, url, **kwargs) as response:
                text = await response.text()
                try:
                    data = await response.json(content_type=None)
                except ValueError:
                    data = None
                if response.status >= 400 or data is None:
                    raise ProviderError(f"HTTP {response.status}: {describe(data, text)}")
                return data
        except aiohttp.ClientError as exc:
            raise ProviderError(f"network error: {exc}") from exc
        except TimeoutError as exc:
            raise ProviderError("the payment service did not answer in time") from exc

    async def close(self) -> None:
        if self.session is not None:
            await self.session.close()
            self.session = None


def describe(data: Any, text: str) -> str:
    if isinstance(data, dict):
        for key in ("description", "error", "message"):
            value = data.get(key)
            if isinstance(value, dict):
                value = value.get("name") or value.get("message")
            if value:
                return str(value)
    return text[:200]


def receipt_body(receipt: Receipt, description: str, amount: Decimal, currency: str, contact: Dict[str, str]) -> Dict[str, Any]:
    customer: Dict[str, str] = {}
    email = contact.get("email")
    phone = contact.get("phone")
    if email:
        customer["email"] = email
    elif phone:
        customer["phone"] = "".join(ch for ch in phone if ch.isdigit())
    if not customer:
        raise ProviderError("a receipt needs the customer's email or phone")
    body: Dict[str, Any] = {
        "customer": customer,
        "items": [{
            "description": description[:128],
            "quantity": "1.00",
            "amount": {"value": money(amount), "currency": currency},
            "vat_code": receipt.vat_code,
            "payment_subject": receipt.payment_subject,
            "payment_mode": receipt.payment_mode,
        }],
    }
    if receipt.tax_system_code:
        body["tax_system_code"] = receipt.tax_system_code
    return body


class YooKassaProvider(Provider):
    def __init__(self, cfg: YooKassa):
        self.cfg = cfg
        self.http = Http()
        token = base64.b64encode(f"{cfg.shop_id}:{cfg.secret_key}".encode()).decode("ascii")
        self.auth = {"Authorization": f"Basic {token}"}

    async def create(self, payment_id: int, amount: Decimal, description: str, contact: Dict[str, str]) -> Created:
        body: Dict[str, Any] = {
            "amount": {"value": money(amount), "currency": self.cfg.currency},
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": self.cfg.return_url},
            "description": description[:128],
            "metadata": {"payment_id": str(payment_id)},
        }
        if self.cfg.receipt:
            body["receipt"] = receipt_body(self.cfg.receipt, description, amount, self.cfg.currency, contact)
        data = await self.http.request(
            "POST", f"{self.cfg.api_base}/payments", json=body,
            headers={**self.auth, "Idempotence-Key": f"funnelbot-{payment_id}-{uuid.uuid4().hex[:8]}"})
        try:
            return Created(str(data["id"]), str(data["confirmation"]["confirmation_url"]))
        except (KeyError, TypeError) as exc:
            raise ProviderError("unexpected answer from YooKassa") from exc

    async def status(self, external_id: str) -> str:
        data = await self.http.request("GET", f"{self.cfg.api_base}/payments/{external_id}", headers=self.auth)
        state = data.get("status") if isinstance(data, dict) else None
        if state == "succeeded":
            return "paid"
        if state == "canceled":
            return "failed"
        return "pending"

    async def check(self) -> str:
        await self.http.request("GET", f"{self.cfg.api_base}/payments?limit=1", headers=self.auth)
        return "credentials accepted"

    async def close(self) -> None:
        await self.http.close()


class CryptoPayProvider(Provider):
    def __init__(self, cfg: Crypto):
        self.cfg = cfg
        self.http = Http()

    @property
    def headers(self) -> Dict[str, str]:
        return {"Crypto-Pay-API-Token": self.cfg.token}

    async def call(self, method: str, http_method: str = "GET", **params: Any) -> Any:
        url = f"{self.cfg.api_base}/{method}"
        if http_method == "POST":
            data = await self.http.request("POST", url, json=params, headers=self.headers)
        else:
            data = await self.http.request("GET", url, params=params, headers=self.headers)
        if not isinstance(data, dict) or not data.get("ok"):
            raise ProviderError(describe(data, "Crypto Pay refused the request"))
        return data.get("result")

    async def create(self, payment_id: int, amount: Decimal, description: str, contact: Dict[str, str]) -> Created:
        result = await self.call(
            "createInvoice", "POST", asset=self.cfg.asset, amount=format(amount.normalize(), "f"),
            description=description[:1024], payload=str(payment_id), expires_in=self.cfg.expires_in,
            allow_comments=False, allow_anonymous=True)
        try:
            return Created(str(result["invoice_id"]), str(result.get("bot_invoice_url") or result["pay_url"]))
        except (KeyError, TypeError) as exc:
            raise ProviderError("unexpected answer from Crypto Pay") from exc

    async def status(self, external_id: str) -> str:
        result = await self.call("getInvoices", invoice_ids=external_id)
        items = result.get("items") if isinstance(result, dict) else result
        if not items:
            return "pending"
        state = items[0].get("status")
        if state == "paid":
            return "paid"
        if state == "expired":
            return "failed"
        return "pending"

    async def check(self) -> str:
        result = await self.call("getMe")
        name = result.get("name") if isinstance(result, dict) else ""
        return f"token accepted (app: {name})" if name else "token accepted"

    async def close(self) -> None:
        await self.http.close()
