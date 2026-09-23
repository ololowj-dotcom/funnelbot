from __future__ import annotations

import html
import json
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .admin import AdminMixin
from .core import format_amount, format_date
from .report import leads_csv
from .transport import Blocked, Btn, Incoming, Keyboard, TransportError

SEGMENT_CODES = ("all", "paid", "unpaid", "active", "expired", "test")


class PanelMixin(AdminMixin):
    def menu(self) -> Keyboard:
        o = self.o
        return [
            [Btn(o("m_stats"), data="ad:s"), Btn(o("m_leads"), data="ad:l")],
            [Btn(o("m_broadcast"), data="ad:b", style="primary"), Btn(o("m_payments"), data="ad:p")],
            [Btn(o("m_find"), data="ad:f"), Btn(o("m_health"), data="ad:h")],
            [Btn(o("m_reload"), data="ad:r")],
        ]

    def back_panel(self) -> Keyboard:
        return [[Btn(self.o("back_panel"), data="ad:m")]]

    def cancel_row(self) -> Keyboard:
        return [[Btn(self.o("cancel"), data="ad:m", style="danger")]]

    def set_wait(self, user_id: int, kind: str) -> None:
        self.store.kv_set(f"wait:{user_id}", kind)

    def get_wait(self, user_id: int) -> str:
        return self.store.kv_get(f"wait:{user_id}") or ""

    def clear_wait(self, user_id: int) -> None:
        self.store.kv_delete(f"wait:{user_id}")

    async def screen(self, inc: Incoming, text: str, keyboard: Optional[Keyboard] = None) -> None:
        body = html.escape(text, quote=False)
        if inc.message_id and inc.callback_id:
            try:
                if await self.transport.edit(inc.chat_id, inc.message_id, body, keyboard, "HTML"):
                    return
            except Blocked:
                return
            except TransportError as exc:
                self.log(f"panel edit failed: {exc}")
        try:
            await self.transport.send(inc.chat_id, body, keyboard, None, "HTML")
        except Blocked:
            return

    async def on_command(self, inc: Incoming, name: str, args: List[str]) -> None:
        if name.lower() == "claim":
            await self.claim(inc, args[0] if args else "")
            return
        await super().on_command(inc, name, args)

    async def cmd_admin(self, inc: Incoming, args: List[str]) -> None:
        self.clear_wait(inc.user_id)
        await self.screen(Incoming(user_id=inc.user_id, chat_id=inc.chat_id), self.o("menu_text"), self.menu())

    async def cmd_panel(self, inc: Incoming, args: List[str]) -> None:
        await self.cmd_admin(inc, args)

    async def claim(self, inc: Incoming, code: str) -> None:
        here = Incoming(user_id=inc.user_id, chat_id=inc.chat_id)
        if self.all_admins() or not self.claim_code or code != self.claim_code:
            await self.screen(here, self.o("claim_no"))
            return
        self.store.kv_set("admins", json.dumps([inc.user_id]))
        await self.screen(here, self.o("claim_ok"), [[Btn(self.o("claim_btn"), data="ad:m", style="success")]])

    async def on_admin_input(self, inc: Incoming) -> bool:
        kind = self.get_wait(inc.user_id)
        if not kind or inc.text.startswith("/"):
            return False
        here = Incoming(user_id=inc.user_id, chat_id=inc.chat_id)
        if kind == "find":
            if not inc.text:
                return False
            self.clear_wait(inc.user_id)
            user = self.lookup_user([inc.text.strip()])
            if user is None:
                await self.screen(here, self.o("find_none"), self.back_panel())
            else:
                await self.user_screen(here, user)
            return True
        if kind == "broadcast":
            self.clear_wait(inc.user_id)
            self.store.kv_set(f"draft:{inc.user_id}", json.dumps({"chat": inc.chat_id, "message": inc.message_id}))
            await self.segment_screen(here)
            return True
        return False

    async def on_panel(self, inc: Incoming) -> None:
        await self.answer(inc)
        if not self.is_admin(inc.user_id):
            return
        parts = inc.data.split(":")
        action, rest = parts[1] if len(parts) > 1 else "m", parts[2:]
        self.clear_wait(inc.user_id)
        handler = getattr(self, f"panel_{action}", None)
        if handler is None:
            await self.screen(inc, self.o("menu_text"), self.menu())
            return
        await handler(inc, rest)

    async def panel_m(self, inc: Incoming, rest: List[str]) -> None:
        await self.screen(inc, self.o("menu_text"), self.menu())

    async def panel_s(self, inc: Incoming, rest: List[str]) -> None:
        await self.screen(inc, self.stats_text(),
                          [[Btn(self.o("refresh"), data="ad:s"), Btn(self.o("back_panel"), data="ad:m")]])

    async def panel_l(self, inc: Incoming, rest: List[str]) -> None:
        await self.transport.send_document_bytes(inc.chat_id, "leads.csv", leads_csv(self.store),
                                                 self.o("leads_caption", n=len(self.store.leads())))

    async def panel_r(self, inc: Incoming, rest: List[str]) -> None:
        await self.screen(inc, self.reload_funnel(), self.back_panel())

    async def panel_h(self, inc: Incoming, rest: List[str]) -> None:
        await self.screen(inc, await self.health_report(),
                          [[Btn(self.o("check_again"), data="ad:h"), Btn(self.o("back_panel"), data="ad:m")]])

    async def health_report(self) -> str:
        o = self.o
        lines: List[str] = []
        for chat in self.managed_chats():
            problem = await self.transport.chat_status(chat)
            lines.append(o("h_channel", icon="❌" if problem else "✅", chat=chat, text=problem or o("h_channel_ok")))
        manager = self.funnel.bot.manager_chat
        lines.append(o("h_manager_set", chat=manager) if manager is not None else o("h_manager_none"))
        for name, provider in self.providers.items():
            try:
                lines.append(o("h_provider_ok", name=name, text=await provider.check()))
            except Exception as exc:
                lines.append(o("h_provider_bad", name=name, error=exc))
        waiting = len(self.store.undelivered())
        lines.append(o("h_waiting", icon="⚠️" if waiting else "✅", n=waiting))
        if not self.funnel.payments.stars:
            lines.append(o("h_stars_off"))
        if self.funnel.bot.test_mode:
            lines.append(o("h_test_mode"))
        lines += [f"⚠️ {w}" for w in self.funnel.warnings[:8]]
        return "\n".join(lines)

    async def panel_b(self, inc: Incoming, rest: List[str]) -> None:
        self.set_wait(inc.user_id, "broadcast")
        await self.screen(inc, self.o("b_prompt"), self.cancel_row())

    async def segment_screen(self, inc: Incoming) -> None:
        now = self.now()
        rows: Keyboard = []
        for i in range(0, len(SEGMENT_CODES), 2):
            rows.append([
                Btn(f"{self.o('seg_' + code)} ({len(self.store.audience(code, now, inc.user_id))})", data=f"ad:bs:{code}")
                for code in SEGMENT_CODES[i:i + 2]
            ])
        rows.append([Btn(self.o("by_step"), data="ad:bg"), Btn(self.o("by_source"), data="ad:bo")])
        rows.append(self.cancel_row()[0])
        await self.screen(inc, self.o("seg_prompt"), rows)

    async def panel_bg(self, inc: Incoming, rest: List[str]) -> None:
        stats = self.store.stats(self.now())["by_step"]
        rows = [[Btn(f"{step} ({n})", data=f"ad:bs:step:{step}")] for step, n in list(stats.items())[:20]]
        rows.append([Btn(self.o("back"), data="ad:bx")])
        await self.screen(inc, self.o("step_prompt"), rows)

    async def panel_bo(self, inc: Incoming, rest: List[str]) -> None:
        stats = self.store.stats(self.now())["by_source"]
        rows = [[Btn(f"{source} ({n})", data=f"ad:bs:source:{source}")] for source, n in list(stats.items())[:20]]
        text = self.o("source_prompt") if rows else self.o("source_none")
        rows.append([Btn(self.o("back"), data="ad:bx")])
        await self.screen(inc, text, rows)

    async def panel_bx(self, inc: Incoming, rest: List[str]) -> None:
        await self.segment_screen(inc)

    async def panel_bs(self, inc: Incoming, rest: List[str]) -> None:
        raw = self.store.kv_get(f"draft:{inc.user_id}")
        if not raw:
            await self.screen(inc, self.o("draft_gone"), self.back_panel())
            return
        draft = json.loads(raw)
        self.store.kv_delete(f"draft:{inc.user_id}")
        await self.prepare_broadcast(inc.chat_id, inc.user_id, draft["chat"], draft["message"], ":".join(rest))

    async def panel_p(self, inc: Incoming, rest: List[str]) -> None:
        rows = self.store.many("SELECT * FROM payments WHERE method != 'grant' ORDER BY id DESC LIMIT 10")
        if not rows:
            await self.screen(inc, self.o("no_payments"), self.back_panel())
            return
        keyboard: Keyboard = []
        for row in rows:
            amount = format_amount(Decimal(row["amount"]), row["currency"])
            label = f"#{row['id']} {row['product_id']} {amount} {self.status_label(row['status'])}"
            keyboard.append([Btn(label, data=f"ad:pd:{row['id']}")])
        keyboard.append([Btn(self.o("back_panel"), data="ad:m")])
        await self.screen(inc, self.o("p_list"), keyboard)

    async def panel_pd(self, inc: Incoming, rest: List[str]) -> None:
        payment = self.store.payment(int(rest[0])) if rest and rest[0].isdigit() else None
        if payment is None:
            await self.screen(inc, self.o("no_order"), self.back_panel())
            return
        keyboard: Keyboard = []
        if payment["status"] == "paid":
            keyboard.append([Btn(self.o("btn_refund"), data=f"ad:rf:{payment['id']}", style="danger")])
        keyboard.append([Btn(self.o("btn_customer"), data=f"ad:u:{payment['user_id']}"),
                         Btn(self.o("back_payments"), data="ad:p")])
        await self.screen(inc, self.o("p_detail", user=payment["user_id"], line=self.payment_titles([payment])[0]), keyboard)

    async def panel_rf(self, inc: Incoming, rest: List[str]) -> None:
        keyboard = [[Btn(self.o("yes_refund"), data=f"ad:rfy:{rest[0]}", style="danger"),
                     Btn(self.o("no_btn"), data=f"ad:pd:{rest[0]}")]]
        await self.screen(inc, self.o("refund_confirm", id=rest[0]), keyboard)

    async def panel_rfy(self, inc: Incoming, rest: List[str]) -> None:
        payment = self.store.payment(int(rest[0])) if rest and rest[0].isdigit() else None
        if payment is None:
            await self.screen(inc, self.o("no_order"), self.back_panel())
            return
        try:
            message = await self.refund_payment(payment)
        except TransportError as exc:
            message = self.o("refund_refused", error=exc)
        await self.screen(inc, message, [[Btn(self.o("back_payments"), data="ad:p")]])

    async def panel_f(self, inc: Incoming, rest: List[str]) -> None:
        self.set_wait(inc.user_id, "find")
        await self.screen(inc, self.o("find_prompt"), self.cancel_row())

    async def user_screen(self, inc: Incoming, user: Dict[str, Any]) -> None:
        uid = user["id"]
        keyboard: Keyboard = [
            [Btn(self.o("u_give"), data=f"ad:gv:{uid}", style="success"), Btn(self.o("u_take"), data=f"ad:tk:{uid}")],
            [Btn(self.o("u_erase"), data=f"ad:er:{uid}", style="danger")],
            [Btn(self.o("back_panel"), data="ad:m")],
        ]
        await self.screen(inc, self.user_summary(user), keyboard)

    async def panel_u(self, inc: Incoming, rest: List[str]) -> None:
        user = self.store.user(int(rest[0])) if rest and rest[0].lstrip("-").isdigit() else None
        if user is None:
            await self.screen(inc, self.o("no_user"), self.back_panel())
            return
        await self.user_screen(inc, user)

    async def panel_gv(self, inc: Incoming, rest: List[str]) -> None:
        rows = [[Btn(p.title, data=f"ad:gr:{rest[0]}:{pid}")] for pid, p in self.funnel.products.items()]
        rows.append([Btn(self.o("back"), data=f"ad:u:{rest[0]}")])
        await self.screen(inc, self.o("give_prompt"), rows)

    async def panel_gr(self, inc: Incoming, rest: List[str]) -> None:
        user = self.store.user(int(rest[0])) if rest and rest[0].lstrip("-").isdigit() else None
        product = self.funnel.products.get(rest[1]) if len(rest) > 1 else None
        if user is None or product is None:
            await self.screen(inc, self.o("unknown_user_product"), self.back_panel())
            return
        await self.give_free(user, product)
        await self.screen(inc, self.o("given", title=product.title, user=user["id"]),
                          [[Btn(self.o("back_customer"), data=f"ad:u:{user['id']}")]])

    async def panel_tk(self, inc: Incoming, rest: List[str]) -> None:
        uid = int(rest[0]) if rest and rest[0].lstrip("-").isdigit() else 0
        grants = self.store.user_grants(uid, only_active=True)
        if not grants:
            await self.screen(inc, self.o("take_none"), [[Btn(self.o("back_customer"), data=f"ad:u:{uid}")]])
            return
        rows = []
        for grant in grants:
            until = format_date(grant["expires_at"]) if grant["expires_at"] else self.o("no_end")
            rows.append([Btn(self.o("grant_until", product=grant["product_id"], until=until), data=f"ad:rv:{grant['id']}")])
        rows.append([Btn(self.o("back"), data=f"ad:u:{uid}")])
        await self.screen(inc, self.o("take_prompt"), rows)

    async def panel_rv(self, inc: Incoming, rest: List[str]) -> None:
        grant = self.store.grant(int(rest[0])) if rest and rest[0].isdigit() else None
        if grant is None:
            await self.screen(inc, self.o("no_access"), self.back_panel())
            return
        removed = await self.revoke_grants([grant])
        note = self.o("taken_ok") if removed else self.o("taken_fail")
        await self.screen(inc, note, [[Btn(self.o("back_customer"), data=f"ad:u:{grant['user_id']}")]])

    async def panel_er(self, inc: Incoming, rest: List[str]) -> None:
        keyboard = [[Btn(self.o("yes_erase"), data=f"ad:ery:{rest[0]}", style="danger"),
                     Btn(self.o("no_btn"), data=f"ad:u:{rest[0]}")]]
        await self.screen(inc, self.o("erase_confirm", user=rest[0]), keyboard)

    async def panel_ery(self, inc: Incoming, rest: List[str]) -> None:
        uid = int(rest[0]) if rest and rest[0].lstrip("-").isdigit() else 0
        await self.revoke_grants(self.store.user_grants(uid, only_active=True))
        self.store.erase_user(uid)
        await self.screen(inc, self.o("erased_done", user=uid), self.back_panel())
