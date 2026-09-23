from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Dict, Optional

from .core import Core, format_amount
from .providers import ProviderError
from .schema import STARS, Receipt
from .transport import Blocked, Btn, Incoming, Invoice, Keyboard, TransportError

REUSE_WINDOW = 1200
OPEN_STATES = ("pending", "expired", "failed")


class PayMixin(Core):
    def method_rows(self, product_id: str, user: Optional[Dict[str, Any]]) -> Keyboard:
        product = self.funnel.products[product_id]
        methods = self.funnel.methods_for(product_id)
        test = self.funnel.bot.test_mode and user is not None and self.is_admin(user["id"])
        style = self.funnel.bot.pay_style
        rows: Keyboard = []
        single = len(methods) == 1 and not test
        for method in methods:
            currency = self.funnel.payments.currency_of(method)
            amount = format_amount(product.prices[currency], currency)
            label = self.tx("pay_now", amount=amount) if single else self.tx(f"pay_{method}", amount=amount)
            rows.append([Btn(label, data=f"m:{product_id}:{method}", style=style)])
        if test:
            currency = next(iter(product.prices))
            rows.append([Btn(self.tx("pay_test", amount=format_amount(product.prices[currency], currency)),
                             data=f"m:{product_id}:test", style="primary")])
        return rows

    async def show_product(self, user: Dict[str, Any], inc: Incoming, product_id: str) -> None:
        product = self.funnel.products.get(product_id)
        if product is None:
            await self.send(inc.chat_id, self.tx("use_buttons"), user_id=inc.user_id)
            return
        rows = self.method_rows(product_id, user)
        if not rows:
            await self.send(inc.chat_id, self.tx("pay_no_method"), user_id=inc.user_id)
            return
        title = f"<b>{self.esc(product.title)}</b>" if self.html else product.title
        parts = [title]
        if product.description:
            parts.append(self.fmt(product.description, user))
        if len(rows) > 1:
            parts.append(self.tx("choose_method", product=product.title))
        text = "\n\n".join(parts)
        if user["step"] in self.funnel.steps:
            rows.append([Btn(self.tx("back"), data=f"g:{user['step']}")])
        sent = False
        if inc.message_id and not product.image and not inc.has_media:
            try:
                sent = await self.transport.edit(inc.chat_id, inc.message_id, text, rows, self.parse_mode)
            except Blocked:
                self.store.update_user(inc.user_id, blocked=1)
                return
            except TransportError:
                sent = False
        if not sent:
            await self.send(inc.chat_id, text, rows, product.image, user_id=inc.user_id)

    def contact(self, user: Dict[str, Any], receipt: Optional[Receipt]) -> Dict[str, str]:
        if receipt is None:
            return {}
        value = (user.get("answers") or {}).get(receipt.contact_key, "")
        if not value:
            return {}
        return {"email": value} if "@" in value else {"phone": value}

    def telegram_receipt(self, receipt: Receipt, title: str, amount: Decimal, currency: str,
                         contact: Dict[str, str]) -> str:
        body: Dict[str, Any] = {
            "items": [{
                "description": title[:128],
                "quantity": 1,
                "amount": {"value": f"{amount:.2f}", "currency": currency},
                "vat_code": receipt.vat_code,
                "payment_mode": receipt.payment_mode,
                "payment_subject": receipt.payment_subject,
            }],
        }
        if receipt.tax_system_code:
            body["tax_system_code"] = receipt.tax_system_code
        if contact:
            body["customer"] = dict(contact)
        return json.dumps({"receipt": body}, ensure_ascii=False)

    async def start_payment(self, user: Dict[str, Any], inc: Incoming, product_id: str, method: str) -> None:
        product = self.funnel.products.get(product_id)
        chat_id, user_id = inc.chat_id, user["id"]
        if product is None:
            await self.send(chat_id, self.tx("use_buttons"), user_id=user_id)
            return
        if method == "test":
            if not (self.funnel.bot.test_mode and self.is_admin(user_id)):
                await self.send(chat_id, self.tx("pay_no_method"), user_id=user_id)
                return
            currency = next(iter(product.prices))
            payment_id = self.store.add_payment(
                user_id, product_id, "test", str(product.prices[currency]), currency, "pending",
                self.now(), user["step"])
            await self.finalize_payment(payment_id)
            return
        if method not in self.funnel.methods_for(product_id):
            await self.send(chat_id, self.tx("pay_no_method"), user_id=user_id)
            return
        currency = self.funnel.payments.currency_of(method) or ""
        amount = product.prices[currency]
        label = format_amount(amount, currency)
        if method in ("stars", "telegram"):
            await self.send_invoice(user, chat_id, product, method, amount, currency)
        elif method == "manual":
            manual = self.funnel.payments.manual
            assert manual is not None
            payment_id = self.store.add_payment(user_id, product_id, "manual", str(amount), currency,
                                                "awaiting_proof", self.now(), user["step"])
            self.store.update_payment(payment_id, meta={"title": product.title})
            instructions = f"<b>{self.esc(product.title)}</b> — {self.esc(label)}\n\n{self.fmt(manual.text, user)}"
            if not self.html:
                instructions = f"{product.title} — {label}\n\n{self.fmt(manual.text, user)}"
            await self.send(chat_id, self.tx("manual_instructions", raw=("instructions",), instructions=instructions),
                            user_id=user_id)
        else:
            await self.send_link_payment(user, chat_id, product, method, amount, currency, label)

    async def send_invoice(self, user: Dict[str, Any], chat_id: int, product: Any, method: str,
                           amount: Decimal, currency: str) -> None:
        payment_id = self.store.add_payment(user["id"], product.id, method, str(amount), currency, "pending",
                                            self.now(), user["step"])
        title = product.title[:32]
        description = (product.description or product.title)[:255]
        if method == "stars":
            invoice = Invoice(
                title=title, description=description, payload=f"p{payment_id}", currency=STARS,
                amount=int(amount), label=product.title[:32], photo=None,
                pay_text=self.tx("pay_now", amount=format_amount(amount, currency)), pay_style=self.funnel.bot.pay_style)
        else:
            cfg = self.funnel.payments.telegram
            assert cfg is not None
            receipt = cfg.receipt
            contact = self.contact(user, receipt)
            need_email = cfg.need_email or (receipt is not None and not contact)
            invoice = Invoice(
                title=title, description=description, payload=f"p{payment_id}", currency=currency,
                amount=int((amount * 100).to_integral_value()), label=product.title[:32],
                provider_token=cfg.provider_token, need_email=need_email,
                send_email_to_provider=receipt is not None and need_email,
                provider_data=self.telegram_receipt(receipt, product.title, amount, currency, contact) if receipt else None,
                pay_text=self.tx("pay_now", amount=format_amount(amount, currency)), pay_style=self.funnel.bot.pay_style)
        try:
            await self.transport.send_invoice(chat_id, invoice)
        except Blocked:
            self.store.update_user(user["id"], blocked=1)
        except TransportError as exc:
            self.store.update_payment(payment_id, status="failed")
            self.log(f"invoice failed: {exc}")
            await self.alert("invoice", self.o("alert_invoice", method=method, error=exc))
            await self.send(chat_id, self.tx("pay_failed"), user_id=user["id"])

    async def send_link_payment(self, user: Dict[str, Any], chat_id: int, product: Any, method: str,
                                amount: Decimal, currency: str, label: str) -> None:
        provider = self.providers.get(method)
        if provider is None:
            await self.send(chat_id, self.tx("pay_no_method"), user_id=user["id"])
            return
        now = self.now()
        payment = self.reusable_payment(user["id"], product.id, method, now)
        if payment is None:
            payment_id = self.store.add_payment(user["id"], product.id, method, str(amount), currency, "pending",
                                                now, user["step"])
            receipt = self.funnel.payments.yookassa.receipt if method == "yookassa" and self.funnel.payments.yookassa else None
            try:
                created = await provider.create(payment_id, amount, product.title, self.contact(user, receipt))
            except ProviderError as exc:
                self.store.update_payment(payment_id, status="failed")
                self.log(f"{method} create failed: {exc}")
                await self.alert(f"create-{method}", self.o("alert_create", method=method, error=exc))
                await self.send(chat_id, self.tx("pay_failed"), user_id=user["id"])
                return
            self.store.update_payment(payment_id, external_id=created.external_id, url=created.url)
            payment = self.store.payment(payment_id)
        assert payment is not None
        title = f"<b>{self.esc(product.title)}</b> — {self.esc(label)}" if self.html else f"{product.title} — {label}"
        keyboard = [
            [Btn(self.tx("pay_now", amount=label), url=payment["url"], style=self.funnel.bot.pay_style)],
            [Btn(self.tx("pay_check"), data=f"k:{payment['id']}")],
        ]
        await self.send(chat_id, f"{title}\n\n{self.tx('pay_waiting')}", keyboard, user_id=user["id"])

    def reusable_payment(self, user_id: int, product_id: str, method: str, now: int) -> Optional[Dict[str, Any]]:
        row = self.store.one(
            "SELECT * FROM payments WHERE user_id = ? AND product_id = ? AND method = ? AND status = 'pending' "
            "AND url IS NOT NULL AND created_at >= ? ORDER BY id DESC LIMIT 1",
            (user_id, product_id, method, now - REUSE_WINDOW))
        return row

    async def poll_one(self, payment: Dict[str, Any]) -> str:
        provider = self.providers.get(payment["method"])
        if provider is None or not payment["external_id"]:
            return payment["status"]
        try:
            state = await provider.status(payment["external_id"])
        except ProviderError as exc:
            self.log(f"status check failed for payment {payment['id']}: {exc}")
            return payment["status"]
        if state == "paid":
            await self.finalize_payment(payment["id"])
            return "paid"
        if state == "failed":
            self.store.update_payment(payment["id"], status="failed")
            return "failed"
        return "pending"

    async def on_check_payment(self, inc: Incoming, user: Dict[str, Any]) -> None:
        payment_id = inc.data[2:]
        payment = self.store.payment(int(payment_id)) if payment_id.isdigit() else None
        if payment is None or payment["user_id"] != inc.user_id:
            await self.answer(inc, self.tx("pay_expired"), True)
            return
        state = payment["status"]
        if state == "pending":
            state = await self.poll_one(payment)
        if state == "paid":
            await self.answer(inc, self.tx("paid_thanks"))
        elif state in ("failed", "expired"):
            await self.answer(inc, self.tx("pay_failed"), True)
        else:
            await self.answer(inc, self.tx("pay_waiting"), True)

    def payment_from_payload(self, payload: str) -> Optional[Dict[str, Any]]:
        if payload.startswith("p") and payload[1:].isdigit():
            return self.store.payment(int(payload[1:]))
        return None

    async def pre_checkout(self, user_id: int, payload: str, currency: str, total: int) -> Optional[str]:
        payment = self.payment_from_payload(payload)
        if payment is None or payment["user_id"] != user_id:
            return self.tx("pay_expired")
        if payment["status"] == "paid":
            return self.tx("paid_thanks")
        if payment["status"] not in OPEN_STATES:
            return self.tx("pay_expired")
        product = self.funnel.products.get(payment["product_id"])
        if product is None:
            return self.tx("pay_no_method")
        expected = Decimal(payment["amount"])
        if payment["method"] == "telegram":
            expected = expected * 100
        if payment["currency"] != currency or int(expected) != total:
            return self.tx("pay_expired")
        return None

    async def on_successful_payment(self, inc: Incoming, payload: str, charge_id: str, currency: str,
                                    total: int, email: str = "") -> None:
        payment = self.payment_from_payload(payload)
        if payment is None or payment["user_id"] != inc.user_id:
            await self.alert(
                f"unmatched-{charge_id}",
                self.o("alert_unmatched", user=inc.user_id, total=total, currency=currency, charge=charge_id,
                       payload=payload))
            return
        if email and not (self.store.user(inc.user_id) or {}).get("answers", {}).get("email"):
            self.store.set_answer(inc.user_id, "email", email)
        if not await self.finalize_payment(payment["id"], charge_id):
            if payment["charge_id"] and payment["charge_id"] != charge_id:
                await self.alert(
                    f"duplicate-{charge_id}",
                    self.o("alert_duplicate", order=payment["id"], first=payment["charge_id"], second=charge_id))

    async def finalize_payment(self, payment_id: int, charge_id: Optional[str] = None) -> bool:
        if not self.store.claim_payment(payment_id, self.now(), charge_id):
            return False
        await self.deliver(payment_id)
        return True

    async def on_proof(self, user: Dict[str, Any], inc: Incoming) -> bool:
        payment = self.store.latest_open_payment(user["id"], ("awaiting_proof",))
        chat = self.funnel.bot.manager_chat
        if payment is None or chat is None:
            return False
        product = self.funnel.products.get(payment["product_id"])
        title = product.title if product else payment["product_id"]
        currency = payment["currency"]
        amount = format_amount(Decimal(payment["amount"]), currency)
        card = self.user_card(user, self.o("card_review"),
                              [self.o("line_order", id=payment["id"], title=title, amount=amount)])
        keyboard = [[Btn(self.o("btn_approve"), data=f"a:{payment['id']}", style="success"),
                     Btn(self.o("btn_reject"), data=f"r:{payment['id']}", style="danger")]]
        try:
            await self.transport.copy_message(chat, inc.chat_id, inc.message_id)
            await self.transport.send(chat, card, keyboard, None, self.parse_mode)
        except TransportError as exc:
            await self.alert("manager-chat", self.o("alert_manager_chat", error=exc))
            return False
        self.store.update_payment(payment["id"], status="review")
        await self.send(inc.chat_id, self.tx("manual_received"), user_id=user["id"])
        return True

    async def on_review(self, inc: Incoming) -> None:
        if not self.is_manager_side(inc):
            await self.answer(inc)
            return
        approve = inc.data.startswith("a:")
        raw = inc.data[2:]
        payment = self.store.payment(int(raw)) if raw.isdigit() else None
        if payment is None or payment["status"] not in ("review", "awaiting_proof"):
            await self.answer(inc, self.o("already_processed"), True)
            return
        await self.answer(inc)
        who = inc.first_name or str(inc.user_id)
        if approve:
            await self.finalize_payment(payment["id"])
            verdict = self.o("verdict_approved", id=payment["id"], who=who)
        else:
            self.store.update_payment(payment["id"], status="rejected")
            await self.send(payment["user_id"], self.tx("manual_rejected"), user_id=payment["user_id"])
            verdict = self.o("verdict_rejected", id=payment["id"], who=who)
        if inc.message_id:
            try:
                await self.transport.edit(inc.chat_id, inc.message_id, self.esc(verdict), None, self.parse_mode)
            except TransportError as exc:
                self.log(f"could not update the review card: {exc}")
