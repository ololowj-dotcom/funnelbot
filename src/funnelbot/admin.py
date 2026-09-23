from __future__ import annotations

import asyncio
import html
import json
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .core import format_amount, format_date
from .loader import FunnelError, load_funnel
from .report import leads_csv
from .sched import SchedMixin
from .transport import Blocked, Btn, Incoming, RetryAfter, TransportError

SEGMENTS = "all, paid, unpaid, active, expired, test, step:<id>, source:<name>"
BROADCAST_DELAY = 0.05
PUBLIC_COMMANDS = ("help", "terms", "paysupport", "deleteme", "stop", "resume", "id")


class AdminMixin(SchedMixin):
    async def plain(self, chat_id: int, text: str, keyboard: Optional[Any] = None) -> None:
        try:
            await self.transport.send(chat_id, html.escape(text, quote=False), keyboard, None, "HTML")
        except Blocked:
            return

    def spawn(self, coroutine: Any) -> None:
        task = asyncio.ensure_future(coroutine)
        self.tasks.append(task)
        task.add_done_callback(lambda t: self.tasks.remove(t) if t in self.tasks else None)

    def yes_no(self, value: Any) -> str:
        return self.o("yes" if value else "no")

    def status_label(self, status: str) -> str:
        key = f"status_{status}"
        return self.o(key) if key in self.owner_keys() else status

    def payment_titles(self, payments: List[Dict[str, Any]]) -> List[str]:
        return [
            f"#{p['id']} {p['product_id']} {p['amount']} {p['currency']} {p['method']} {self.status_label(p['status'])}"
            for p in payments
        ]

    async def on_command(self, inc: Incoming, name: str, args: List[str]) -> None:
        name = name.lower()
        if name in PUBLIC_COMMANDS:
            await self.public_command(inc, name)
            return
        if not self.is_admin(inc.user_id):
            return
        handler = getattr(self, f"cmd_{name}", None)
        if handler is None:
            await self.plain(inc.chat_id, self.o("unknown_command"))
            return
        try:
            await handler(inc, args)
        except TransportError as exc:
            await self.plain(inc.chat_id, self.o("telegram_refused", error=exc))

    async def public_command(self, inc: Incoming, name: str) -> None:
        if name == "id":
            await self.plain(inc.chat_id, self.o("your_id", user=inc.user_id, chat=inc.chat_id))
            return
        user = self.touch(inc)
        if name == "help":
            await self.send(inc.chat_id, self.tx("help"), user_id=inc.user_id)
        elif name == "terms":
            await self.cmd_terms(inc)
        elif name == "paysupport":
            rows = [[Btn(self.tx("contact_manager"), data="mg")]] if self.funnel.bot.manager_chat is not None else None
            await self.send(inc.chat_id, self.tx("paysupport"), rows, user_id=inc.user_id)
        elif name == "deleteme":
            rows = [[Btn(self.tx("yes"), data="del:y", style="danger"), Btn(self.tx("no"), data="del:n")]]
            await self.send(inc.chat_id, self.tx("deleteme_ask"), rows, user_id=inc.user_id)
        elif name == "stop":
            self.store.update_user(inc.user_id, stopped=1)
            await self.send(inc.chat_id, self.tx("stopped"), user_id=inc.user_id)
        elif name == "resume":
            self.store.update_user(user["id"], stopped=0)
            await self.send(inc.chat_id, self.tx("resumed"), user_id=inc.user_id)

    async def cmd_terms(self, inc: Incoming) -> None:
        consent = self.funnel.consent
        if consent is None or not consent.documents:
            await self.send(inc.chat_id, self.tx("terms"), user_id=inc.user_id)
            return
        rows = [[Btn(d.title, url=d.url)] for d in consent.documents]
        await self.send(inc.chat_id, self.tx("terms"), rows, user_id=inc.user_id)

    async def on_delete_button(self, inc: Incoming) -> None:
        await self.answer(inc)
        if inc.data == "del:y":
            grants = self.store.user_grants(inc.user_id, only_active=True)
            await self.revoke_grants(grants)
            for grant in self.store.user_grants(inc.user_id, only_active=True):
                self.store.update_grant(grant["id"], status="ended", ended_at=self.now())
            self.store.erase_user(inc.user_id)
            text = self.tx("deleted")
        else:
            text = self.tx("no")
        try:
            if inc.message_id:
                await self.transport.edit(inc.chat_id, inc.message_id, text, None, self.parse_mode)
            else:
                await self.send(inc.chat_id, text, user_id=inc.user_id)
        except TransportError as exc:
            self.log(f"delete confirmation failed: {exc}")

    async def cmd_stats(self, inc: Incoming, args: List[str]) -> None:
        await self.plain(inc.chat_id, self.stats_text())

    def stats_text(self) -> str:
        s = self.store.stats(self.now())
        share = f"{s['buyers'] * 100 / s['users']:.1f}%" if s["users"] else "0%"
        lines = [
            self.o("stats_users", users=s["users"], day=s["new_day"], week=s["new_week"], blocked=s["blocked"]),
            self.o("stats_buyers", buyers=s["buyers"], share=share, payments=s["payments"], refunded=s["refunded"],
                   pending=s["pending"]),
            self.o("stats_access", n=s["active_access"]),
        ]
        for currency, bucket in sorted(s["revenue"].items()):
            lines.append(self.o(
                "stats_revenue", currency=currency,
                total=format_amount(Decimal(str(bucket["total"])), currency),
                week=format_amount(Decimal(str(bucket["week"])), currency),
                day=format_amount(Decimal(str(bucket["day"])), currency)))
        if s["by_step"]:
            lines.append(self.o("stats_steps", items=", ".join(f"{k} {v}" for k, v in list(s["by_step"].items())[:12])))
        if s["by_source"]:
            lines.append(self.o("stats_sources", items=", ".join(f"{k} {v}" for k, v in list(s["by_source"].items())[:12])))
        return "\n".join(lines)

    async def cmd_leads(self, inc: Incoming, args: List[str]) -> None:
        content = leads_csv(self.store)
        await self.transport.send_document_bytes(inc.chat_id, "leads.csv", content,
                                                 self.o("leads_caption", n=len(self.store.leads())))

    async def cmd_payments(self, inc: Incoming, args: List[str]) -> None:
        rows = self.store.many("SELECT * FROM payments ORDER BY id DESC LIMIT 15")
        if not rows:
            await self.plain(inc.chat_id, self.o("no_payments"))
            return
        word = self.o("user_word")
        await self.plain(inc.chat_id, "\n".join(
            f"{word} {r['user_id']} " + line for r, line in zip(rows, self.payment_titles(rows), strict=True)))

    def user_summary(self, user: Dict[str, Any]) -> str:
        lines = [
            f"id {user['id']} @{user['username']} {user['first_name']}",
            self.o("user_line", source=user["source"] or "-", step=user["step"] or "-",
                   consent=self.yes_no(user["consented_at"]), blocked=self.yes_no(user["blocked"]),
                   stopped=self.yes_no(user["stopped"]), erased=self.yes_no(user["erased"])),
        ]
        if user["answers"]:
            lines.append(self.o("user_answers", answers=json.dumps(user["answers"], ensure_ascii=False)))
        lines += [self.o("user_payment", line=t) for t in self.payment_titles(self.store.user_payments(user["id"]))]
        for grant in self.store.user_grants(user["id"]):
            until = format_date(grant["expires_at"]) if grant["expires_at"] else self.o("no_end")
            lines.append(self.o("user_access", product=grant["product_id"], chat=grant["chat"], until=until,
                                status=self.status_label(grant["status"])))
        return "\n".join(lines)

    async def cmd_user(self, inc: Incoming, args: List[str]) -> None:
        user = self.lookup_user(args)
        if user is None:
            await self.plain(inc.chat_id, self.o("usage_user"))
            return
        await self.plain(inc.chat_id, self.user_summary(user))

    def lookup_user(self, args: List[str]) -> Optional[Dict[str, Any]]:
        if not args:
            return None
        key = args[0]
        if key.lstrip("-").isdigit():
            return self.store.user(int(key))
        return self.store.one("SELECT * FROM users WHERE lower(username) = ?", (key.lstrip("@").lower(),))

    async def cmd_grant(self, inc: Incoming, args: List[str]) -> None:
        if len(args) < 2:
            await self.plain(inc.chat_id, self.o("usage_grant"))
            return
        user = self.lookup_user(args)
        product = self.funnel.products.get(args[1])
        if user is None or user["erased"]:
            await self.plain(inc.chat_id, self.o("user_not_started"))
            return
        if product is None:
            await self.plain(inc.chat_id, self.o("unknown_product", items=", ".join(self.funnel.products)))
            return
        await self.give_free(user, product)
        await self.plain(inc.chat_id, self.o("granted", product=product.id, user=user["id"]))

    async def give_free(self, user: Dict[str, Any], product: Any) -> None:
        currency = next(iter(product.prices))
        payment_id = self.store.add_payment(user["id"], product.id, "grant", "0", currency, "pending", self.now())
        await self.finalize_payment(payment_id)

    async def cmd_revoke(self, inc: Incoming, args: List[str]) -> None:
        if len(args) < 2:
            await self.plain(inc.chat_id, self.o("usage_revoke"))
            return
        user = self.lookup_user(args)
        if user is None:
            await self.plain(inc.chat_id, self.o("unknown_user"))
            return
        grants = [g for g in self.store.user_grants(user["id"], only_active=True) if g["product_id"] == args[1]]
        if not grants:
            await self.plain(inc.chat_id, self.o("no_active_access"))
            return
        removed = await self.revoke_grants(grants)
        left = len(grants) - removed
        note = self.o("revoke_left", left=left) if left else ""
        await self.plain(inc.chat_id, self.o("revoked", removed=removed, total=len(grants), note=note))

    async def refund_payment(self, payment: Dict[str, Any]) -> str:
        if payment["status"] != "paid":
            return self.o("refund_not_paid", id=payment["id"], status=self.status_label(payment["status"]))
        if payment["method"] == "stars" and payment["charge_id"]:
            await self.transport.refund_stars(payment["user_id"], payment["charge_id"])
            note = self.o("refund_stars")
        elif payment["method"] in ("test", "grant"):
            note = self.o("refund_fake")
        else:
            note = self.o("refund_manual", method=payment["method"])
        self.store.update_payment(payment["id"], status="refunded")
        grants = self.store.many("SELECT * FROM grants WHERE payment_id = ? AND status = 'active'", (payment["id"],))
        removed = await self.revoke_grants(grants)
        return self.o("refund_done", id=payment["id"], removed=removed, note=note)

    async def cmd_refund(self, inc: Incoming, args: List[str]) -> None:
        payment = self.store.payment(int(args[0])) if args and args[0].isdigit() else None
        if payment is None:
            await self.plain(inc.chat_id, self.o("usage_refund"))
            return
        await self.plain(inc.chat_id, await self.refund_payment(payment))

    async def cmd_erase(self, inc: Incoming, args: List[str]) -> None:
        user = self.lookup_user(args)
        if user is None:
            await self.plain(inc.chat_id, self.o("usage_erase"))
            return
        await self.revoke_grants(self.store.user_grants(user["id"], only_active=True))
        self.store.erase_user(user["id"])
        await self.plain(inc.chat_id, self.o("erased", user=user["id"]))

    def reload_funnel(self) -> str:
        if not self.funnel_path:
            return self.o("reload_na")
        try:
            funnel = load_funnel(self.funnel_path)
        except FunnelError as exc:
            return self.o("reload_errors", errors=str(exc)[:3000])
        changed = funnel.payments != self.funnel.payments
        self.apply_funnel(funnel)
        lines = [self.o("reload_ok", steps=len(funnel.steps), products=len(funnel.products))]
        if changed:
            lines.append(self.o("reload_payments"))
        lines += [self.o("reload_warning", warning=w) for w in funnel.warnings[:10]]
        return "\n".join(lines)

    async def cmd_reload(self, inc: Incoming, args: List[str]) -> None:
        await self.plain(inc.chat_id, self.reload_funnel())

    async def prepare_broadcast(self, chat_id: int, admin_id: int, source_chat: int, source_message: int, segment: str) -> None:
        try:
            ids = self.store.audience(segment, self.now(), admin_id)
        except ValueError:
            await self.plain(chat_id, self.o("bc_unknown_segment", segments=SEGMENTS))
            return
        if not ids:
            await self.plain(chat_id, self.o("bc_nobody"))
            return
        broadcast_id = self.store.add_broadcast(admin_id, source_chat, source_message, segment, len(ids), self.now())
        keyboard = [[Btn(self.o("bc_send", n=len(ids)), data=f"bc:{broadcast_id}:y", style="success"),
                     Btn(self.o("cancel"), data=f"bc:{broadcast_id}:n", style="danger")]]
        await self.plain(chat_id, self.o("bc_ask", n=len(ids), segment=segment), keyboard)

    async def cmd_broadcast(self, inc: Incoming, args: List[str]) -> None:
        if not inc.reply_to:
            await self.plain(inc.chat_id, self.o("bc_hint", segments=SEGMENTS))
            return
        await self.prepare_broadcast(inc.chat_id, inc.user_id, inc.reply_chat or inc.chat_id, inc.reply_to,
                                     args[0] if args else "all")

    async def on_broadcast_button(self, inc: Incoming) -> None:
        parts = inc.data.split(":")
        broadcast = self.store.broadcast(int(parts[1])) if len(parts) == 3 and parts[1].isdigit() else None
        if broadcast is None or not self.is_admin(inc.user_id):
            await self.answer(inc)
            return
        if broadcast["status"] != "draft":
            await self.answer(inc, self.o("bc_handled"), True)
            return
        await self.answer(inc)
        if parts[2] != "y":
            self.store.update_broadcast(broadcast["id"], status="cancelled")
            verdict = self.o("bc_cancelled")
        else:
            ids = self.store.audience(broadcast["segment"], self.now(), broadcast["admin_id"])
            self.store.kv_set(f"bc:{broadcast['id']}", json.dumps(ids))
            self.store.update_broadcast(broadcast["id"], status="running", total=len(ids))
            self.spawn(self.run_broadcast(broadcast["id"]))
            verdict = self.o("bc_started", n=len(ids))
        if inc.message_id:
            try:
                await self.transport.edit(inc.chat_id, inc.message_id, html.escape(verdict), None, "HTML")
            except TransportError as exc:
                self.log(f"broadcast card update failed: {exc}")

    async def run_broadcast(self, broadcast_id: int, delay: float = BROADCAST_DELAY) -> None:
        broadcast = self.store.broadcast(broadcast_id)
        raw = self.store.kv_get(f"bc:{broadcast_id}")
        if broadcast is None or raw is None or broadcast["status"] != "running":
            return
        ids: List[int] = json.loads(raw)
        cursor, sent, failed = broadcast["cursor"], broadcast["sent"], broadcast["failed"]
        while cursor < len(ids):
            uid = ids[cursor]
            try:
                await self.transport.copy_message(uid, broadcast["chat_id"], broadcast["message_id"])
                sent += 1
            except Blocked:
                self.store.update_user(uid, blocked=1)
                failed += 1
            except RetryAfter as exc:
                await asyncio.sleep(min(exc.seconds, 60))
                continue
            except TransportError as exc:
                self.log(f"broadcast to {uid} failed: {exc}")
                failed += 1
            cursor += 1
            if cursor % 20 == 0:
                self.store.update_broadcast(broadcast_id, cursor=cursor, sent=sent, failed=failed)
            if delay:
                await asyncio.sleep(delay)
        self.store.update_broadcast(broadcast_id, cursor=cursor, sent=sent, failed=failed, status="done")
        self.store.kv_delete(f"bc:{broadcast_id}")
        await self.plain(broadcast["admin_id"], self.o("bc_finished", sent=sent, failed=failed))

    def resume_broadcasts(self) -> None:
        for broadcast in self.store.running_broadcasts():
            self.spawn(self.run_broadcast(broadcast["id"]))
