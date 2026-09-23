from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class TransportError(Exception):
    pass


class Blocked(TransportError):
    pass


class RetryAfter(TransportError):
    def __init__(self, seconds: float):
        super().__init__(f"retry after {seconds}s")
        self.seconds = seconds


class NotFound(TransportError):
    pass


@dataclass
class Btn:
    text: str
    data: Optional[str] = None
    url: Optional[str] = None
    copy: Optional[str] = None
    style: Optional[str] = None
    icon: Optional[str] = None


Keyboard = List[List[Btn]]


@dataclass
class Invoice:
    title: str
    description: str
    payload: str
    currency: str
    amount: int
    label: str
    provider_token: Optional[str] = None
    need_email: bool = False
    send_email_to_provider: bool = False
    provider_data: Optional[str] = None
    photo: Optional[str] = None
    file_id: str = ""
    file_kind: str = ""
    pay_text: Optional[str] = None
    pay_style: Optional[str] = None


@dataclass
class Incoming:
    user_id: int
    chat_id: int
    username: str = ""
    first_name: str = ""
    text: str = ""
    data: str = ""
    callback_id: str = ""
    message_id: int = 0
    has_media: bool = False
    photo: Optional[str] = None
    file_id: str = ""
    file_kind: str = ""
    reply_to: int = 0
    reply_chat: int = 0
    payload: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


class Transport:
    async def send(self, chat_id: int, text: str, keyboard: Optional[Keyboard] = None, image: Optional[str] = None,
                   parse_mode: Optional[str] = "HTML") -> int:
        raise NotImplementedError

    async def edit(self, chat_id: int, message_id: int, text: str, keyboard: Optional[Keyboard] = None,
                   parse_mode: Optional[str] = "HTML") -> bool:
        raise NotImplementedError

    async def clear_keyboard(self, chat_id: int, message_id: int) -> None:
        raise NotImplementedError

    async def send_file(self, chat_id: int, file: str, caption: str = "", parse_mode: Optional[str] = "HTML") -> Optional[str]:
        raise NotImplementedError

    async def send_document_bytes(self, chat_id: int, name: str, content: bytes, caption: str = "") -> None:
        raise NotImplementedError

    async def send_invoice(self, chat_id: int, invoice: Invoice) -> int:
        raise NotImplementedError

    async def answer_callback(self, callback_id: str, text: str = "", alert: bool = False) -> None:
        raise NotImplementedError

    async def create_join_link(self, chat: int, name: str) -> str:
        raise NotImplementedError

    async def approve_join(self, chat: int, user_id: int) -> None:
        raise NotImplementedError

    async def decline_join(self, chat: int, user_id: int) -> None:
        raise NotImplementedError

    async def remove_member(self, chat: int, user_id: int) -> None:
        raise NotImplementedError

    async def refund_stars(self, user_id: int, charge_id: str) -> None:
        raise NotImplementedError

    async def copy_message(self, to_chat: int, from_chat: int, message_id: int,
                           keyboard: Optional[Keyboard] = None) -> int:
        raise NotImplementedError

    async def is_member(self, chat: int, user_id: int) -> bool:
        raise NotImplementedError

    async def chat_status(self, chat: int) -> str:
        raise NotImplementedError
