from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple

from .providers import Created, Provider, ProviderError
from .transport import Blocked, Btn, Invoice, Keyboard, NotFound, Transport


@dataclass
class Sent:
    chat_id: int
    message_id: int
    text: str
    keyboard: Keyboard = field(default_factory=list)
    image: Optional[str] = None
    kind: str = "text"
    edited: bool = False


class RecordingTransport(Transport):
    def __init__(self) -> None:
        self.messages: List[Sent] = []
        self.files: List[Tuple[int, str, str]] = []
        self.documents: List[Tuple[int, str, bytes]] = []
        self.invoices: List[Tuple[int, Invoice]] = []
        self.callbacks: List[Tuple[str, str, bool]] = []
        self.links: Dict[int, str] = {}
        self.link_calls = 0
        self.approved: List[Tuple[int, int]] = []
        self.declined: List[Tuple[int, int]] = []
        self.removed: List[Tuple[int, int]] = []
        self.refunds: List[Tuple[int, str]] = []
        self.copies: List[Tuple[int, int, int]] = []
        self.blocked: Set[int] = set()
        self.members: Set[Tuple[int, int]] = set()
        self.remove_failures = 0
        self.next_id = 100
        self.cleared: List[Tuple[int, int]] = []
        self.chat_problems: Dict[int, str] = {}

    def bump(self) -> int:
        self.next_id += 1
        return self.next_id

    def guard(self, chat_id: int) -> None:
        if chat_id in self.blocked:
            raise Blocked("blocked")

    async def send(self, chat_id, text, keyboard=None, image=None, parse_mode="HTML"):
        self.guard(chat_id)
        message_id = self.bump()
        self.messages.append(Sent(chat_id, message_id, text, keyboard or [], image, "photo" if image else "text"))
        return message_id

    async def edit(self, chat_id, message_id, text, keyboard=None, parse_mode="HTML"):
        self.guard(chat_id)
        for message in self.messages:
            if message.chat_id == chat_id and message.message_id == message_id:
                message.text = text
                message.keyboard = keyboard or []
                message.edited = True
                return True
        return False

    async def clear_keyboard(self, chat_id, message_id):
        self.cleared.append((chat_id, message_id))
        for message in self.messages:
            if message.chat_id == chat_id and message.message_id == message_id:
                message.keyboard = []

    async def send_file(self, chat_id, file, caption="", parse_mode="HTML"):
        self.guard(chat_id)
        self.files.append((chat_id, file, caption))
        return f"file_id:cached-{len(self.files)}"

    async def send_document_bytes(self, chat_id, name, content, caption=""):
        self.guard(chat_id)
        self.documents.append((chat_id, name, content))

    async def send_invoice(self, chat_id, invoice):
        self.guard(chat_id)
        self.invoices.append((chat_id, invoice))
        return self.bump()

    async def answer_callback(self, callback_id, text="", alert=False):
        self.callbacks.append((callback_id, text, alert))

    async def create_join_link(self, chat, name):
        self.link_calls += 1
        link = f"https://t.me/+link{abs(chat)}"
        self.links[chat] = link
        return link

    async def approve_join(self, chat, user_id):
        self.approved.append((chat, user_id))
        self.members.add((chat, user_id))

    async def decline_join(self, chat, user_id):
        self.declined.append((chat, user_id))

    async def remove_member(self, chat, user_id):
        if self.remove_failures > 0:
            self.remove_failures -= 1
            raise NotFound("cannot remove right now")
        self.removed.append((chat, user_id))
        self.members.discard((chat, user_id))

    async def refund_stars(self, user_id, charge_id):
        self.refunds.append((user_id, charge_id))

    async def copy_message(self, to_chat, from_chat, message_id, keyboard=None):
        self.guard(to_chat)
        self.copies.append((to_chat, from_chat, message_id))
        message_new = self.bump()
        self.messages.append(Sent(to_chat, message_new, f"<copy of {from_chat}:{message_id}>", keyboard or [], None, "copy"))
        return message_new

    async def is_member(self, chat, user_id):
        return (chat, user_id) in self.members

    async def chat_status(self, chat):
        return self.chat_problems.get(chat, "")

    def to(self, chat_id: int) -> List[Sent]:
        return [m for m in self.messages if m.chat_id == chat_id]

    def last(self, chat_id: int) -> Sent:
        return self.to(chat_id)[-1]

    def texts(self, chat_id: int) -> List[str]:
        return [m.text for m in self.to(chat_id)]

    def buttons(self, chat_id: int) -> List[Btn]:
        return [b for row in self.last(chat_id).keyboard for b in row]

    def data_for(self, chat_id: int, label: str) -> str:
        for button in self.buttons(chat_id):
            if label.lower() in button.text.lower() and button.data:
                return button.data
        labels = [b.text for b in self.buttons(chat_id)]
        raise AssertionError(f"no button containing '{label}' in {labels}")

    def find(self, chat_id: int, needle: str) -> Optional[Sent]:
        for message in reversed(self.to(chat_id)):
            if needle.lower() in message.text.lower():
                return message
        return None


class FakeProvider(Provider):
    def __init__(self, base_url: str = "https://pay.example/") -> None:
        self.base_url = base_url
        self.created: List[Tuple[int, Decimal, str, Dict[str, str]]] = []
        self.states: Dict[str, str] = {}
        self.fail_create = False
        self.fail_status = False

    async def create(self, payment_id, amount, description, contact):
        if self.fail_create:
            raise ProviderError("provider is down")
        self.created.append((payment_id, amount, description, contact))
        external = f"ext-{len(self.created)}"
        self.states[external] = "pending"
        return Created(external, f"{self.base_url}{external}")

    async def status(self, external_id):
        if self.fail_status:
            raise ProviderError("provider is down")
        return self.states.get(external_id, "pending")

    async def check(self):
        return "fake ok"
