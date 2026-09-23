from __future__ import annotations

import asyncio
import html
import re
from typing import Any, Callable, Dict, Iterable, Optional

from .engine import Engine
from .fake import FakeProvider, RecordingTransport
from .schema import Funnel, parse_duration
from .store import Store
from .transport import Incoming, Keyboard

DOTS = {"primary": "🟦", "success": "🟩", "danger": "🟥"}
TAGS = re.compile(r"</?[a-z]+[^>]*>")
HELP = """Type a number to press a button, any other text to send a message.
/start [source]   restart the funnel (also /help /stats /leads ... as an admin)
:pay              simulate the customer paying the last invoice or link
:photo            send a payment screenshot (manual payment)
:approve / :reject  act as the manager on the last payment card
:join             ask to join every private channel of the funnel
:tick 3d          move time forward (nudges, reminders, expiry)
:as admin|user    switch who is talking to the bot
:state            show what the bot stored about you
:quit             leave"""


def plain(text: str) -> str:
    return html.unescape(TAGS.sub("", text))


class ConsoleTransport(RecordingTransport):
    def __init__(self, out: Callable[[str], None], manager_chat: Optional[int]):
        super().__init__()
        self.out = out
        self.manager_chat = manager_chat
        self.keyboards: Dict[int, Keyboard] = {}

    def show(self, chat_id: int, text: str, keyboard: Optional[Keyboard], note: str = "") -> None:
        label = "manager chat" if chat_id == self.manager_chat else "bot"
        self.out(f"\n[{label}]{note} " + plain(text).replace("\n", "\n      "))
        if keyboard:
            self.keyboards[chat_id] = keyboard
            number = 0
            for row in keyboard:
                cells = []
                for button in row:
                    number += 1
                    extra = ""
                    if button.url:
                        extra = f" -> {button.url}"
                    elif button.copy:
                        extra = f" (copies {button.copy})"
                    cells.append(f"[{number}] {DOTS.get(button.style or '', '')} {button.text}{extra}".replace("  ", " "))
                self.out("      " + "   ".join(cells))

    async def send(self, chat_id, text, keyboard=None, image=None, parse_mode="HTML"):
        message_id = await super().send(chat_id, text, keyboard, image, parse_mode)
        self.show(chat_id, text, keyboard, " (with picture)" if image else "")
        return message_id

    async def edit(self, chat_id, message_id, text, keyboard=None, parse_mode="HTML"):
        done = await super().edit(chat_id, message_id, text, keyboard, parse_mode)
        if done:
            self.show(chat_id, text, keyboard)
        return done

    async def send_file(self, chat_id, file, caption="", parse_mode="HTML"):
        self.out(f"\n[bot] sends the file {file}")
        return await super().send_file(chat_id, file, caption, parse_mode)

    async def send_document_bytes(self, chat_id, name, content, caption=""):
        self.out(f"\n[bot] sends {name} ({len(content)} bytes): {caption}")
        await super().send_document_bytes(chat_id, name, content, caption)

    async def send_invoice(self, chat_id, invoice):
        message_id = await super().send_invoice(chat_id, invoice)
        price = invoice.amount if invoice.currency == "XTR" else invoice.amount / 100
        self.out(f"\n[bot] INVOICE {invoice.title}: {price:g} {invoice.currency}   [{DOTS.get(invoice.pay_style or '', '')} {invoice.pay_text}]")
        self.out("      type :pay to simulate the payment")
        return message_id

    async def create_join_link(self, chat, name):
        link = await super().create_join_link(chat, name)
        self.out(f"\n[telegram] join-request link created for chat {chat}")
        return link

    async def approve_join(self, chat, user_id):
        await super().approve_join(chat, user_id)
        self.out(f"\n[telegram] join request of {user_id} APPROVED in {chat}")

    async def decline_join(self, chat, user_id):
        await super().decline_join(chat, user_id)
        self.out(f"\n[telegram] join request of {user_id} DECLINED in {chat}")

    async def remove_member(self, chat, user_id):
        await super().remove_member(chat, user_id)
        self.out(f"\n[telegram] {user_id} removed from {chat}")

    async def copy_message(self, to_chat, from_chat, message_id, keyboard=None):
        self.out(f"\n[telegram] message copied to {to_chat}")
        return await super().copy_message(to_chat, from_chat, message_id, keyboard)

    async def refund_stars(self, user_id, charge_id):
        self.out(f"\n[telegram] Stars refunded to {user_id}")
        await super().refund_stars(user_id, charge_id)


class Preview:
    def __init__(self, funnel: Funnel, out: Callable[[str], None] = print):
        self.out = out
        self.funnel = funnel
        self.transport = ConsoleTransport(out, funnel.bot.manager_chat)
        self.clock_value = 1_800_000_000
        self.provider = FakeProvider()
        providers = {m: self.provider for m in ("yookassa", "crypto") if getattr(funnel.payments, m)}
        self.engine = Engine(funnel, Store(":memory:"), self.transport, providers, clock=lambda: self.clock_value)
        self.admin_id = funnel.bot.admins[0] if funnel.bot.admins else 1
        self.user_id = 1000 if self.admin_id != 1000 else 1001
        self.seq = 0

    def me(self, **extra: Any) -> Incoming:
        return Incoming(user_id=self.user_id, chat_id=self.user_id, username="preview_user", first_name="Preview", **extra)

    async def start(self) -> None:
        self.out("funnelbot preview: talking to your funnel as a test customer. Nothing is sent to Telegram.")
        self.out("Type :help for the commands.")
        await self.engine.on_start(self.me())

    async def handle(self, line: str) -> bool:
        line = line.strip()
        if not line:
            return True
        if line in (":quit", ":q", ":exit"):
            return False
        if line.startswith(":"):
            await self.control(line)
        elif line.startswith("/"):
            name, *args = line[1:].split()
            if name == "start":
                await self.engine.on_start(self.me(payload=args[0] if args else ""))
            else:
                await self.engine.on_command(self.me(reply_to=1, reply_chat=self.user_id), name, args)
        elif line.isdigit():
            await self.press(int(line))
        else:
            await self.engine.on_text(self.me(text=line))
        return True

    async def press(self, number: int, chat: Optional[int] = None) -> None:
        chat = chat or self.user_id
        buttons = [b for row in self.transport.keyboards.get(chat, []) for b in row]
        if not 1 <= number <= len(buttons):
            self.out("There is no such button.")
            return
        button = buttons[number - 1]
        if not button.data:
            self.out("(that is a link or copy button: nothing happens in the console)")
            return
        messages = self.transport.to(chat)
        message_id = messages[-1].message_id if messages else 0
        self.seq += 1
        who = self.me(data=button.data, message_id=message_id, callback_id=f"p{self.seq}")
        if chat == self.transport.manager_chat:
            who = Incoming(user_id=self.admin_id, chat_id=chat, first_name="Manager", data=button.data,
                           message_id=message_id, callback_id=f"p{self.seq}")
        await self.engine.on_callback(who)

    async def control(self, line: str) -> None:
        name, *args = line[1:].split()
        if name == "help":
            self.out(HELP)
        elif name == "tick":
            seconds = parse_duration(args[0]) if args else None
            if seconds is None:
                self.out("Usage: :tick 30m | 2h | 3d")
                return
            self.clock_value += seconds
            self.out(f"(time moved forward by {args[0]})")
            await self.engine.tick()
        elif name == "as":
            self.user_id = self.admin_id if args and args[0] == "admin" else (1000 if self.admin_id != 1000 else 1001)
            self.out(f"(now talking as {'admin' if self.user_id == self.admin_id else 'a customer'}, id {self.user_id})")
        elif name == "pay":
            await self.pay()
        elif name == "photo":
            await self.engine.on_photo(self.me(message_id=77, photo="preview"))
        elif name in ("approve", "reject"):
            await self.review(name == "approve")
        elif name == "join":
            for chat in sorted(self.engine.managed_chats()):
                await self.engine.on_join_request(chat, self.user_id, self.user_id)
        elif name == "state":
            self.state()
        else:
            self.out("Unknown control. Type :help")

    async def pay(self) -> None:
        pending = self.engine.store.latest_open_payment(self.user_id, ("pending",))
        if pending is None:
            self.out("Nothing to pay: choose a product first.")
            return
        if pending["method"] in ("stars", "telegram"):
            invoice = next((i for _, i in reversed(self.transport.invoices) if i.payload == f"p{pending['id']}"), None)
            if invoice is None:
                self.out("The invoice is gone, start again.")
                return
            problem = await self.engine.pre_checkout(self.user_id, invoice.payload, invoice.currency, invoice.amount)
            if problem:
                self.out(f"[telegram] pre-checkout refused: {problem}")
                return
            await self.engine.on_successful_payment(self.me(), invoice.payload, f"preview-{pending['id']}",
                                                    invoice.currency, invoice.amount)
        else:
            for key in self.provider.states:
                self.provider.states[key] = "paid"
            self.clock_value += self.funnel.payments.poll_seconds + 1
            self.engine.last_poll = 0
            await self.engine.tick()

    async def review(self, approve: bool) -> None:
        keyboard = self.transport.keyboards.get(self.transport.manager_chat or 0)
        if not keyboard:
            self.out("There is no payment card waiting in the manager chat.")
            return
        await self.press(1 if approve else 2, self.transport.manager_chat)

    def state(self) -> None:
        store = self.engine.store
        user = store.user(self.user_id)
        self.out(f"user: {user}")
        for payment in store.user_payments(self.user_id):
            self.out(f"payment: {payment['product_id']} {payment['amount']} {payment['currency']} {payment['method']} {payment['status']}")
        for grant in store.user_grants(self.user_id):
            self.out(f"access: {grant['product_id']} chat {grant['chat']} until {grant['expires_at']} {grant['status']}")


async def read_line() -> Optional[str]:
    try:
        return await asyncio.to_thread(input, "> ")
    except EOFError:
        return None


async def run_preview(funnel: Funnel, lines: Optional[Iterable[str]] = None,
                      out: Callable[[str], None] = print) -> Preview:
    preview = Preview(funnel, out)
    await preview.start()
    scripted = iter(lines) if lines is not None else None
    while True:
        line = next(scripted, None) if scripted is not None else await read_line()
        if line is None or not await preview.handle(line):
            break
        await asyncio.sleep(0)
    for task in list(preview.engine.tasks):
        task.cancel()
    return preview
