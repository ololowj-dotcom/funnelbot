import asyncio
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from funnelbot.loader import parse_funnel

BASE = {
    "bot": {"language": "en", "admins": [1], "manager_chat": -100500},
    "payments": {"stars": True},
    "products": {
        "club": {
            "title": "Club",
            "description": "Closed channel",
            "prices": {"XTR": 500},
            "access": [{"channel": {"chat": -100123, "days": 30, "remind_days": [3, 1]}}],
        },
        "guide": {
            "title": "Guide",
            "prices": {"XTR": 100},
            "access": [{"message": {"text": "Hello {first_name}"}}],
        },
    },
    "start": "welcome",
    "steps": {
        "welcome": {
            "text": "Hi {first_name}",
            "buttons": [[{"text": "Offer", "goto": "offer"}]],
        },
        "offer": {
            "text": "Choose",
            "paid": "thanks",
            "buttons": [
                [{"text": "Club", "pay": "club"}],
                [{"text": "Guide", "pay": "guide", "style": "success"}],
                [{"text": "Back", "back": True}],
            ],
        },
        "thanks": {"text": "Thanks", "end": True},
    },
}


@pytest.fixture
def raw():
    return copy.deepcopy(BASE)


@pytest.fixture
def build(tmp_path):
    def make(data, env=None):
        return parse_funnel(data, env or {}, tmp_path)

    return make


class Clock:
    def __init__(self, start=1_800_000_000):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class World:
    def __init__(self, engine, store, transport, clock):
        self.engine = engine
        self.store = store
        self.transport = transport
        self.clock = clock
        self.seq = 0

    def run(self, coro):
        return asyncio.run(coro)

    def known(self, uid, kwargs):
        user = self.store.user(uid)
        if user and "username" not in kwargs:
            kwargs["username"] = user["username"]
        return kwargs

    async def start(self, uid, payload="", **kwargs):
        await self.engine.on_start(incoming(uid, payload=payload, **kwargs))

    async def press(self, uid, label=None, data=None, **kwargs):
        last = self.transport.last(uid)
        if data is None:
            data = self.transport.data_for(uid, label)
        self.seq += 1
        await self.engine.on_callback(
            incoming(uid, data=data, message_id=last.message_id, callback_id=f"cb{self.seq}", **self.known(uid, kwargs)))

    async def say(self, uid, text, **kwargs):
        await self.engine.on_text(incoming(uid, text=text, **kwargs))

    async def command(self, uid, name, *args, **kwargs):
        await self.engine.on_command(incoming(uid, **kwargs), name, list(args))

    async def tick(self, seconds=0):
        self.clock.advance(seconds)
        await self.engine.tick()

    async def pay_stars(self, uid, invoice_index=-1, charge="ch1"):
        _, invoice = self.transport.invoices[invoice_index]
        problem = await self.engine.pre_checkout(uid, invoice.payload, invoice.currency, invoice.amount)
        assert problem is None, problem
        await self.engine.on_successful_payment(incoming(uid, **self.known(uid, {})), invoice.payload, charge, invoice.currency, invoice.amount)


def incoming(user_id, **kwargs):
    from funnelbot.transport import Incoming

    kwargs.setdefault("chat_id", user_id)
    kwargs.setdefault("first_name", f"User{user_id}")
    return Incoming(user_id=user_id, **kwargs)


@pytest.fixture
def world(raw, tmp_path):
    from funnelbot.engine import Engine
    from funnelbot.fake import RecordingTransport
    from funnelbot.store import Store

    def make(mutate=None, providers=None, env=None):
        if mutate:
            mutate(raw)
        funnel = parse_funnel(raw, env or {}, tmp_path)
        store = Store(":memory:")
        transport = RecordingTransport()
        clock = Clock()
        engine = Engine(funnel, store, transport, providers or {}, clock=clock, log=lambda m: None)
        return World(engine, store, transport, clock)

    return make
