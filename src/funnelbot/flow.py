from __future__ import annotations

from typing import Any, Dict, List, Optional

from .core import MAX_CHAIN, MAX_HISTORY, Core, normalize_answer
from .schema import Step
from .transport import Blocked, Btn, Incoming, Keyboard, TransportError

MANAGER_COOLDOWN = 600


class FlowMixin(Core):
    def touch(self, inc: Incoming) -> Dict[str, Any]:
        user = self.store.upsert_user(inc.user_id, inc.username, inc.first_name, self.now())
        if user["blocked"]:
            self.store.update_user(inc.user_id, blocked=0)
            user["blocked"] = 0
        return user

    def needs_consent(self, user: Dict[str, Any]) -> bool:
        return self.funnel.consent is not None and not user["consented_at"]

    async def answer(self, inc: Incoming, text: str = "", alert: bool = False) -> None:
        if inc.callback_id:
            self.answered.add(inc.callback_id)
            try:
                await self.transport.answer_callback(inc.callback_id, text, alert)
            except TransportError as exc:
                self.log(f"answer_callback failed: {exc}")

    async def on_start(self, inc: Incoming) -> None:
        user = self.touch(inc)
        if self.is_admin(inc.user_id):
            self.clear_wait(inc.user_id)
        if inc.payload.startswith("claim_"):
            await self.claim(inc, inc.payload[len("claim_"):])
            return
        if inc.payload and not user["source"]:
            self.store.update_user(inc.user_id, source=inc.payload[:64])
            user["source"] = inc.payload[:64]
        if self.needs_consent(user):
            await self.consent_screen(user, inc.chat_id)
            return
        await self.enter_step(inc.user_id, inc.chat_id, self.funnel.start, reset=True)

    async def consent_screen(self, user: Dict[str, Any], chat_id: int, nag: bool = False) -> None:
        consent = self.funnel.consent
        if consent is None:
            return
        text = self.fmt(consent.text, user)
        if nag:
            text = self.tx("consent_needed") + "\n\n" + text
        rows: Keyboard = [[Btn(d.title, url=d.url)] for d in consent.documents]
        rows.append([Btn(consent.agree or self.tx("agree"), data="c", style="success")])
        await self.send(chat_id, text, rows, user_id=user["id"])

    async def on_consent(self, inc: Incoming) -> None:
        user = self.touch(inc)
        await self.answer(inc)
        if not user["consented_at"]:
            self.store.update_user(inc.user_id, consented_at=self.now())
        if inc.message_id:
            try:
                await self.transport.clear_keyboard(inc.chat_id, inc.message_id)
            except TransportError as exc:
                self.log(f"clear keyboard failed: {exc}")
        await self.enter_step(inc.user_id, inc.chat_id, self.funnel.start, reset=True)

    def step_keyboard(self, step: Step, user: Dict[str, Any]) -> Keyboard:
        rows: Keyboard = []
        if step.pay and step.pay in self.funnel.products:
            rows += self.method_rows(step.pay, user)
        if step.ask and step.ask.kind == "choice":
            for i in range(0, len(step.ask.choices), 2):
                rows.append([Btn(c, data=f"ans:{i + n}") for n, c in enumerate(step.ask.choices[i:i + 2])])
        rows += self.keyboard(step.buttons)
        return rows

    async def enter_step(self, user_id: int, chat_id: int, step_id: str, edit: int = 0, has_media: bool = False,
                         push: bool = True, reset: bool = False, depth: int = 0) -> None:
        step = self.funnel.steps.get(step_id)
        if step is None:
            step_id = self.funnel.start
            step = self.funnel.steps[step_id]
        user = self.store.user(user_id)
        if user is None:
            return
        history: List[str] = [] if reset else list(user["history"])
        if push and user["step"] and user["step"] != step_id and not reset:
            history.append(user["step"])
        history = history[-MAX_HISTORY:]
        now = self.now()
        advance = now + step.wait if step.next and not step.ask and step.wait else None
        self.store.update_user(user_id, step=step_id, step_at=now, advance_at=advance, history=history)
        self.store.clear_nudges(user_id)
        user = self.store.user(user_id)
        text = self.fmt(step.text, user)
        keyboard = self.step_keyboard(step, user)
        sent = False
        if edit and not step.image and not has_media:
            try:
                sent = await self.transport.edit(chat_id, edit, text, keyboard, self.parse_mode)
            except Blocked:
                self.store.update_user(user_id, blocked=1)
                return
            except TransportError:
                sent = False
        if not sent:
            if await self.send(chat_id, text, keyboard, step.image, user_id=user_id) is None:
                return
        if step.next and not step.ask and not step.buttons and not step.pay and not step.wait and depth < MAX_CHAIN:
            await self.enter_step(user_id, chat_id, step.next, depth=depth + 1)

    async def go_back(self, inc: Incoming) -> None:
        user = self.store.user(inc.user_id)
        history = list(user["history"]) if user else []
        while history and history[-1] not in self.funnel.steps:
            history.pop()
        target = history.pop() if history else self.funnel.start
        self.store.update_user(inc.user_id, history=history)
        await self.enter_step(inc.user_id, inc.chat_id, target, inc.message_id, inc.has_media, push=False)

    async def on_callback(self, inc: Incoming) -> None:
        data = inc.data
        if data.startswith(("a:", "r:")):
            await self.on_review(inc)
            return
        if data.startswith("bc:"):
            await self.on_broadcast_button(inc)
            return
        if data.startswith("ad:"):
            await self.on_panel(inc)
            return
        if data.startswith("del:"):
            await self.on_delete_button(inc)
            return
        if data == "c":
            await self.on_consent(inc)
            return
        user = self.touch(inc)
        if data.startswith("k:"):
            await self.on_check_payment(inc, user)
            return
        await self.answer(inc)
        if self.needs_consent(user):
            await self.consent_screen(user, inc.chat_id, nag=True)
            return
        if data.startswith("g:"):
            await self.enter_step(inc.user_id, inc.chat_id, data[2:], inc.message_id, inc.has_media)
        elif data == "b":
            await self.go_back(inc)
        elif data == "h":
            await self.enter_step(inc.user_id, inc.chat_id, self.funnel.start, inc.message_id, inc.has_media, reset=True)
        elif data == "mg":
            await self.call_manager(user, inc.chat_id)
        elif data.startswith("p:"):
            await self.show_product(user, inc, data[2:])
        elif data.startswith("m:"):
            _, _, rest = data.partition(":")
            product_id, _, method = rest.rpartition(":")
            await self.start_payment(user, inc, product_id, method)
        elif data.startswith("ans:"):
            await self.on_choice(inc, user, data[4:])
        else:
            await self.send(inc.chat_id, self.tx("use_buttons"), user_id=inc.user_id)

    async def on_choice(self, inc: Incoming, user: Dict[str, Any], index: str) -> None:
        step = self.funnel.steps.get(user["step"])
        if not step or not step.ask or not index.isdigit() or int(index) >= len(step.ask.choices):
            await self.send(inc.chat_id, self.tx("use_buttons"), user_id=inc.user_id)
            return
        await self.submit_answer(user, inc.chat_id, step, step.ask.choices[int(index)])

    async def submit_answer(self, user: Dict[str, Any], chat_id: int, step: Step, value: str) -> None:
        assert step.ask is not None
        self.store.set_answer(user["id"], step.ask.key, value)
        await self.enter_step(user["id"], chat_id, step.next or self.funnel.start)

    async def on_text(self, inc: Incoming) -> None:
        user = self.touch(inc)
        if self.is_admin(inc.user_id) and await self.on_admin_input(inc):
            return
        if self.needs_consent(user):
            await self.consent_screen(user, inc.chat_id, nag=True)
            return
        step = self.funnel.steps.get(user["step"])
        if step and step.ask:
            value = normalize_answer(step.ask, inc.text)
            if value is None:
                message = step.ask.error or self.tx(f"invalid_{step.ask.kind}" if step.ask.kind != "text" else "use_buttons")
                await self.send(inc.chat_id, message, user_id=inc.user_id)
                return
            await self.submit_answer(user, inc.chat_id, step, value)
            return
        await self.send(inc.chat_id, self.tx("use_buttons"), user_id=inc.user_id)

    async def on_photo(self, inc: Incoming) -> None:
        user = self.touch(inc)
        if self.is_admin(inc.user_id) and await self.on_admin_input(inc):
            return
        if self.needs_consent(user):
            await self.consent_screen(user, inc.chat_id, nag=True)
            return
        if await self.on_proof(user, inc):
            return
        await self.send(inc.chat_id, self.tx("use_buttons"), user_id=inc.user_id)

    def user_card(self, user: Dict[str, Any], title: str, lines: Optional[List[str]] = None) -> str:
        name = self.esc(user.get("first_name") or user["id"])
        who = f'<a href="tg://user?id={user["id"]}">{name}</a>' if self.html else str(name)
        handle = f" @{self.esc(user['username'])}" if user.get("username") else ""
        parts = [f"<b>{self.esc(title)}</b>" if self.html else title, f"{who}{handle} (id {user['id']})"]
        if user.get("source"):
            parts.append(self.esc(self.o("line_source", source=user["source"])))
        for key, value in (user.get("answers") or {}).items():
            parts.append(f"{self.esc(key)}: {self.esc(value)}")
        parts += lines or []
        return "\n".join(parts)

    async def call_manager(self, user: Dict[str, Any], chat_id: int) -> None:
        chat = self.funnel.bot.manager_chat
        if chat is None:
            return
        now = self.now()
        key = f"manager:{user['id']}"
        if now - self.alerted.get(key, 0) >= MANAGER_COOLDOWN:
            self.alerted[key] = now
            try:
                await self.transport.send(chat, self.user_card(user, self.o("card_manager"), [self.o("line_step", step=user["step"])]),
                                          None, None, self.parse_mode)
            except TransportError as exc:
                self.log(f"manager card failed: {exc}")
                await self.alert("manager-chat", self.o("alert_manager_chat", error=exc))
        await self.send(chat_id, self.tx("manager_called"), user_id=user["id"])
