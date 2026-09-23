from __future__ import annotations

import math
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, List, Set

from .core import DAY, format_amount, format_date
from .pay import PayMixin
from .transport import Blocked, Btn, TransportError

RETRY_DELIVERY = 60
MAX_BACKOFF = 3600


class AccessMixin(PayMixin):
    async def ensure_link(self, chat: int) -> str:
        key = f"link:{chat}"
        cached = self.store.kv_get(key)
        if cached:
            return cached
        link = await self.transport.create_join_link(chat, "funnelbot")
        self.store.kv_set(key, link)
        return link

    def managed_chats(self) -> Set[int]:
        chats = {a.chat for p in self.funnel.products.values() for a in p.access if a.kind == "channel" and a.chat is not None}
        chats |= {g["chat"] for g in self.store.active_grants()}
        return chats

    def save_done(self, payment_id: int, meta: Dict[str, Any], done: Set[str]) -> None:
        meta = dict(meta)
        meta["done"] = sorted(done)
        self.store.update_payment(payment_id, meta=meta)

    async def deliver(self, payment_id: int) -> None:
        if payment_id in self.delivering:
            return
        self.delivering.add(payment_id)
        try:
            await self.deliver_once(payment_id)
        finally:
            self.delivering.discard(payment_id)

    async def deliver_once(self, payment_id: int) -> None:
        payment = self.store.payment(payment_id)
        if payment is None or payment["delivered"]:
            return
        user = self.store.user(payment["user_id"])
        if user is None:
            self.store.update_payment(payment_id, delivered=1)
            return
        product = self.funnel.products.get(payment["product_id"])
        meta = dict(payment["meta"])
        done: Set[str] = set(meta.get("done", []))
        chat = user["id"]

        async def once(name: str, action: Callable[[], Awaitable[Any]]) -> None:
            if name in done:
                return
            await action()
            done.add(name)
            self.save_done(payment_id, meta, done)

        try:
            thanks = self.tx("manual_approved" if payment["method"] == "manual" else "paid_thanks")
            await once("thanks", lambda: self.send(chat, thanks, user_id=chat))
            if product is None:
                await self.alert(f"gone-{payment['product_id']}",
                                 self.o("alert_gone", order=payment_id, product=payment["product_id"]))
            else:
                for index, rule in enumerate(product.access):
                    await once(f"a{index}", lambda rule=rule: self.give(rule, user, product, payment))
            origin = self.funnel.steps.get(payment["origin_step"] or "")
            if origin is not None and origin.paid:
                await once("next", lambda: self.enter_step(chat, chat, origin.paid))
        except Blocked:
            self.store.update_user(chat, blocked=1)
        except (TransportError, OSError) as exc:
            self.retry_at[payment_id] = self.now() + RETRY_DELIVERY
            self.log(f"delivery of order {payment_id} will be retried: {exc}")
            await self.alert(f"deliver-{payment_id}", self.o("alert_deliver", order=payment_id, error=exc))
            return
        self.store.update_payment(payment_id, delivered=1)
        self.retry_at.pop(payment_id, None)

    async def give(self, rule: Any, user: Dict[str, Any], product: Any, payment: Dict[str, Any]) -> None:
        if rule.kind == "channel":
            await self.give_channel(rule, user, product, payment)
        elif rule.kind == "message":
            text = self.fmt(rule.text, user, product=product.title)
            if text.strip():
                await self.send(user["id"], text, user_id=user["id"])
            for file in rule.files:
                await self.send_cached_file(user["id"], file)
        else:
            await self.give_manager(rule, user, product, payment)

    async def send_cached_file(self, chat_id: int, file: str) -> None:
        key = f"file:{file}"
        source = self.store.kv_get(key) or file
        try:
            file_id = await self.transport.send_file(chat_id, source, "", self.parse_mode)
        except Blocked:
            self.store.update_user(chat_id, blocked=1)
            return
        if file_id and not file.startswith("file_id:"):
            self.store.kv_set(key, file_id)

    async def give_manager(self, rule: Any, user: Dict[str, Any], product: Any, payment: Dict[str, Any]) -> None:
        chat = self.funnel.bot.manager_chat
        if chat is not None:
            currency = payment["currency"]
            lines = [self.o("line_paid", id=payment["id"], title=product.title, method=payment["method"],
                            amount=format_amount(Decimal(payment["amount"]), currency))]
            try:
                await self.transport.send(chat, self.user_card(user, self.o("card_paid"), lines), None, None, self.parse_mode)
            except TransportError as exc:
                await self.alert("manager-chat", self.o("alert_manager_chat", error=exc))
        text = self.fmt(rule.text, user, product=product.title) if rule.text.strip() else self.tx("manager_called")
        await self.send(user["id"], text, user_id=user["id"])

    async def give_channel(self, rule: Any, user: Dict[str, Any], product: Any, payment: Dict[str, Any]) -> None:
        now = self.now()
        uid = user["id"]
        grant = self.store.live_grant_for_product(uid, product.id, rule.chat)
        if grant is None:
            expires = now + rule.days * DAY if rule.days else None
            grant_id = self.store.add_grant(uid, product.id, payment["id"], rule.chat, expires, now)
            renewal = False
        else:
            grant_id = grant["id"]
            if grant["expires_at"] is None or not rule.days:
                expires = None
            else:
                expires = max(now, grant["expires_at"]) + rule.days * DAY
            self.store.update_grant(grant_id, expires_at=expires, reminded=[], remove_attempts=0, next_try=0)
            renewal = True
        until = self.tx("access_until", date=format_date(expires)) if expires else ""
        member = bool(grant and grant["joined"])
        if renewal and not member:
            try:
                member = await self.transport.is_member(rule.chat, uid)
            except TransportError:
                member = False
        if renewal and member:
            await self.send(uid, self.tx("access_renewed", product=product.title, until=until), user_id=uid)
            return
        link = await self.ensure_link(rule.chat)
        await self.send(uid, self.tx("access_channel", product=product.title, until=until, link=link), user_id=uid)

    async def on_join_request(self, chat: int, user_id: int, user_chat_id: int) -> None:
        if chat not in self.managed_chats():
            return
        grant = self.store.live_grant(user_id, chat)
        now = self.now()
        allowed = grant is not None and (grant["expires_at"] is None or grant["expires_at"] > now)
        try:
            if allowed:
                await self.transport.approve_join(chat, user_id)
            else:
                await self.transport.decline_join(chat, user_id)
        except TransportError as exc:
            self.log(f"join request of {user_id} in {chat} could not be answered: {exc}")
            await self.alert(f"join-{chat}", self.o("alert_join", chat=chat, error=exc))
            return
        if allowed and grant is not None:
            self.store.update_grant(grant["id"], joined=1)
        await self.send(user_chat_id or user_id, self.tx("join_approved" if allowed else "join_declined"), user_id=user_id)

    async def expire(self, grant: Dict[str, Any], force: bool = False) -> bool:
        now = self.now()
        uid = grant["user_id"]
        if not force and now < grant["next_try"]:
            return False
        others = [g for g in self.store.user_grants(uid, only_active=True)
                  if g["id"] != grant["id"] and g["chat"] == grant["chat"]
                  and (g["expires_at"] is None or g["expires_at"] > now)]
        if (self.funnel.bot.enforce_expiry or force) and not others:
            try:
                await self.transport.remove_member(grant["chat"], uid)
            except TransportError as exc:
                attempts = grant["remove_attempts"] + 1
                delay = min(60 * 2 ** (attempts - 1), MAX_BACKOFF)
                self.store.update_grant(grant["id"], remove_attempts=attempts, next_try=now + delay)
                self.log(f"could not remove {uid} from {grant['chat']} (attempt {attempts}): {exc}")
                if attempts >= 3:
                    await self.alert(f"remove-{grant['id']}",
                                     self.o("alert_remove", user=uid, chat=grant["chat"], tries=attempts, error=exc))
                return False
        self.store.update_grant(grant["id"], status="ended", ended_at=now, joined=0)
        product = self.funnel.products.get(grant["product_id"])
        title = product.title if product else grant["product_id"]
        keyboard = [[Btn(self.tx("renew"), data=f"p:{grant['product_id']}", style=self.funnel.bot.pay_style)]] if product else None
        await self.send(uid, self.tx("access_expired", product=title), keyboard, user_id=uid)
        return True

    async def remind(self, grant: Dict[str, Any], now: int) -> None:
        product = self.funnel.products.get(grant["product_id"])
        if product is None:
            return
        rule = next((a for a in product.access if a.kind == "channel" and a.chat == grant["chat"]), None)
        if rule is None or not rule.remind:
            return
        left = grant["expires_at"] - now
        reminded: List[int] = list(grant["reminded"])
        due = [d for d in rule.remind if left <= d * DAY and d not in reminded]
        if not due:
            return
        days_left = max(1, math.ceil(left / DAY))
        self.store.update_grant(grant["id"], reminded=reminded + due)
        keyboard = [[Btn(self.tx("renew"), data=f"p:{product.id}", style=self.funnel.bot.pay_style)]]
        await self.send(grant["user_id"], self.tx("access_reminder", product=product.title, days=days_left), keyboard,
                        user_id=grant["user_id"])

    async def run_access(self) -> None:
        now = self.now()
        for grant in self.store.active_grants():
            if grant["expires_at"] is None:
                continue
            try:
                if grant["expires_at"] <= now:
                    await self.expire(grant)
                else:
                    await self.remind(grant, now)
            except Exception as exc:
                self.log(f"access job for grant {grant['id']} failed: {exc!r}")

    async def revoke_grants(self, grants: List[Dict[str, Any]]) -> int:
        removed = 0
        for grant in grants:
            if grant["status"] != "active":
                continue
            if await self.expire(grant, force=True):
                removed += 1
        return removed
