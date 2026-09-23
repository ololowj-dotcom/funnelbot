from __future__ import annotations

import copy
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .loader import FunnelError, load_funnel
from .schema import Funnel

STYLES = {"blue": "primary", "green": "success", "red": "danger", "plain": None}
ASK_KEYS = {"text": "name", "email": "email", "phone": "phone", "number": "number"}
DELAYS = {"1h": "1h", "3h": "3h", "1d": "1d", "3d": "3d"}


class BuildError(Exception):
    pass


def dump_yaml(data: Dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False, width=1000)


def read_raw(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise BuildError("the funnel file is not a mapping")
    return data


def write_checked(path: Path, data: Dict[str, Any], env: Optional[Dict[str, str]] = None) -> Funnel:
    path = Path(path)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(dump_yaml(data), encoding="utf-8")
    try:
        funnel = load_funnel(temp, env)
    except FunnelError as exc:
        temp.unlink(missing_ok=True)
        raise BuildError(str(exc)) from exc
    if path.exists():
        shutil.copyfile(path, path.with_name(path.name + ".bak"))
    os.replace(temp, path)
    return funnel


class Draft:
    def __init__(self, data: Dict[str, Any]):
        self.data = data
        self.data.setdefault("steps", {})
        self.data.setdefault("products", {})

    @property
    def steps(self) -> Dict[str, Any]:
        return self.data["steps"]

    @property
    def products(self) -> Dict[str, Any]:
        return self.data["products"]

    def step(self, sid: str) -> Dict[str, Any]:
        if sid not in self.steps:
            raise BuildError(f"no such step: {sid}")
        return self.steps[sid]

    def product(self, pid: str) -> Dict[str, Any]:
        if pid not in self.products:
            raise BuildError(f"no such product: {pid}")
        return self.products[pid]

    def free_id(self, prefix: str, taken: Dict[str, Any]) -> str:
        n = 1
        while f"{prefix}_{n}" in taken:
            n += 1
        return f"{prefix}_{n}"

    @property
    def start(self) -> str:
        return str(self.data.get("start") or next(iter(self.steps), ""))

    def add_step(self, text: str) -> str:
        sid = self.free_id("step", self.steps)
        self.steps[sid] = {"text": text}
        if not self.data.get("start"):
            self.data["start"] = sid
        return sid

    def set_text(self, sid: str, text: str) -> None:
        self.step(sid)["text"] = text

    def set_image(self, sid: str, ref: Optional[str]) -> None:
        step = self.step(sid)
        if ref:
            step["image"] = ref
        else:
            step.pop("image", None)

    def add_button(self, sid: str, button: Dict[str, Any]) -> None:
        step = self.step(sid)
        if step.get("ask"):
            raise BuildError("a question step cannot have buttons")
        step.setdefault("buttons", []).append([button])

    def buttons_of(self, sid: str) -> List[Tuple[int, int, Dict[str, Any]]]:
        found = []
        for r, row in enumerate(self.step(sid).get("buttons") or []):
            for i, button in enumerate(row):
                found.append((r, i, button))
        return found

    def remove_button(self, sid: str, r: int, i: int) -> None:
        rows = self.step(sid).get("buttons") or []
        if not (0 <= r < len(rows) and 0 <= i < len(rows[r])):
            raise BuildError("no such button")
        del rows[r][i]
        self.tidy(sid)

    def tidy(self, sid: str) -> None:
        step = self.step(sid)
        rows = [row for row in (step.get("buttons") or []) if row]
        if rows:
            step["buttons"] = rows
        else:
            step.pop("buttons", None)
        for nudge in step.get("nudges") or []:
            rows = [row for row in (nudge.get("buttons") or []) if row]
            if rows:
                nudge["buttons"] = rows
            else:
                nudge.pop("buttons", None)

    def add_nudge(self, sid: str, after: str, text: str) -> None:
        step = self.step(sid)
        nudge: Dict[str, Any] = {"after": after, "text": text}
        if step.get("buttons"):
            nudge["buttons"] = copy.deepcopy(step["buttons"])
        step.setdefault("nudges", []).append(nudge)

    def remove_nudge(self, sid: str, index: int) -> None:
        nudges = self.step(sid).get("nudges") or []
        if not 0 <= index < len(nudges):
            raise BuildError("no such reminder")
        del nudges[index]
        if not nudges:
            self.step(sid).pop("nudges", None)

    def set_question(self, sid: str, kind: str, nxt: str) -> str:
        step = self.step(sid)
        self.step(nxt)
        base = ASK_KEYS[kind]
        used = {s["ask"]["key"] for s in self.steps.values() if isinstance(s.get("ask"), dict) and s is not step}
        key, n = base, 2
        while key in used:
            key, n = f"{base}_{n}", n + 1
        step["ask"] = {"key": key, "type": kind}
        step["next"] = nxt
        step.pop("buttons", None)
        step.pop("pay", None)
        for nudge in step.get("nudges") or []:
            nudge.pop("buttons", None)
        return key

    def clear_question(self, sid: str) -> None:
        step = self.step(sid)
        step.pop("ask", None)
        step.pop("next", None)

    def remove_step(self, sid: str) -> None:
        self.step(sid)
        if sid == self.start:
            raise BuildError("the start step cannot be deleted")
        del self.steps[sid]
        for other_id, other in self.steps.items():
            if other.get("next") == sid:
                other.pop("next", None)
                other.pop("ask", None)
            if other.get("paid") == sid:
                other.pop("paid", None)
            for rows in [other.get("buttons")] + [n.get("buttons") for n in other.get("nudges") or []]:
                for row in rows or []:
                    row[:] = [b for b in row if b.get("goto") != sid]
            self.tidy(other_id)

    def set_start(self, sid: str) -> None:
        self.step(sid)
        self.data["start"] = sid

    def add_product(self, title: str, description: str, prices: Dict[str, Any]) -> str:
        pid = self.free_id("product", self.products)
        product: Dict[str, Any] = {"title": title}
        if description:
            product["description"] = description
        product["prices"] = dict(prices)
        product["access"] = []
        self.products[pid] = product
        return pid

    def set_price(self, pid: str, currency: str, value: Any) -> None:
        self.product(pid).setdefault("prices", {})[currency] = value

    def remove_price(self, pid: str, currency: str) -> None:
        prices = self.product(pid).get("prices", {})
        if len(prices) <= 1:
            raise BuildError("a product needs at least one price")
        prices.pop(currency, None)

    def add_access(self, pid: str, item: Dict[str, Any]) -> None:
        self.product(pid).setdefault("access", []).append(item)

    def remove_access(self, pid: str, index: int) -> None:
        items = self.product(pid).get("access") or []
        if not 0 <= index < len(items):
            raise BuildError("no such access item")
        del items[index]

    def remove_product(self, pid: str) -> None:
        self.product(pid)
        del self.products[pid]
        for sid, step in self.steps.items():
            if step.get("pay") == pid:
                step.pop("pay", None)
            for rows in [step.get("buttons")] + [n.get("buttons") for n in step.get("nudges") or []]:
                for row in rows or []:
                    row[:] = [b for b in row if b.get("pay") != pid]
            self.tidy(sid)

    def payments(self) -> Dict[str, Any]:
        return self.data.setdefault("payments", {})

    def set_stars(self, on: bool) -> None:
        if on:
            self.payments()["stars"] = True
        else:
            self.payments().pop("stars", None)

    def set_test_mode(self, on: bool) -> None:
        self.data.setdefault("bot", {})["test_mode"] = on

    def set_manager_chat(self, chat: int) -> None:
        self.data.setdefault("bot", {})["manager_chat"] = chat

    def set_language(self, language: str) -> None:
        self.data.setdefault("bot", {})["language"] = language


def button_dict(text: str, action: str, value: Any = True, color: str = "plain") -> Dict[str, Any]:
    button: Dict[str, Any] = {"text": text, action: value}
    style = STYLES.get(color)
    if style:
        button["style"] = style
    return button


def channel_item(chat: int, days: Optional[int]) -> Dict[str, Any]:
    body: Dict[str, Any] = {"chat": chat}
    if days:
        body["days"] = days
        if days > 3:
            body["remind_days"] = [3, 1]
        elif days > 1:
            body["remind_days"] = [1]
    return {"channel": body}


def message_item(text: str, file_ref: Optional[str]) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    if text:
        body["text"] = text
    if file_ref:
        body["files"] = [file_ref]
    return {"message": body}
