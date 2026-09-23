from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .builder import (
    ASK_KEYS,
    DELAYS,
    STYLES,
    BuildError,
    Draft,
    button_dict,
    channel_item,
    message_item,
    read_raw,
    write_checked,
)
from .core import format_amount
from .panel import PanelMixin
from .schema import STARS
from .transport import Btn, Incoming, Keyboard, TransportError

MAX_LIST = 40
DAYS = (("7", 7), ("30", 30), ("90", 90), ("365", 365))
COLOR_EMOJI = {"primary": "🔵", "success": "🟢", "danger": "🔴"}


def clip(text: str, size: int = 24) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= size else text[: size - 1] + "…"


class BuilderMixin(PanelMixin):
    def menu(self) -> Keyboard:
        rows = super().menu()
        rows.insert(1, [Btn(self.o("m_build"), data="ad:w", style="success")])
        return rows

    def clear_wait(self, user_id: int) -> None:
        super().clear_wait(user_id)
        self.store.kv_delete(f"bw:{user_id}")

    def set_bw(self, user_id: int, kind: str, **context: Any) -> None:
        self.store.kv_set(f"bw:{user_id}", json.dumps({"kind": kind, **context}))

    def get_bw(self, user_id: int) -> Dict[str, Any]:
        raw = self.store.kv_get(f"bw:{user_id}")
        return json.loads(raw) if raw else {}

    def get_pending(self, user_id: int) -> Dict[str, Any]:
        raw = self.store.kv_get(f"bd:{user_id}")
        return json.loads(raw) if raw else {}

    def set_pending(self, user_id: int, **values: Any) -> None:
        self.store.kv_set(f"bd:{user_id}", json.dumps(values))

    def drop_pending(self, user_id: int) -> None:
        self.store.kv_delete(f"bd:{user_id}")

    def back_to(self, data: str, key: str = "back") -> Keyboard:
        return [[Btn(self.o(key), data=data)]]

    def cancel_to(self, data: str) -> Keyboard:
        return [[Btn(self.o("cancel"), data=data, style="danger")]]

    async def edit_funnel(self, inc: Incoming, action: Callable[[Draft], Any]) -> tuple:
        if not self.funnel_path:
            await self.screen(inc, self.o("w_unavailable"), self.back_to("ad:m", "back_panel"))
            return False, None
        path = Path(self.funnel_path)
        try:
            draft = Draft(read_raw(path))
            result = action(draft)
            funnel = write_checked(path, draft.data)
        except BuildError as exc:
            await self.screen(inc, self.o("w_error", error=str(exc)[:1500]), self.back_to("ad:w"))
            return False, None
        self.apply_funnel(funnel)
        return True, result

    def raw(self) -> Draft:
        return Draft(read_raw(Path(self.funnel_path))) if self.funnel_path else Draft({})

    def step_label(self, draft: Draft, sid: str) -> str:
        star = "⭐ " if sid == draft.start else ""
        return f"{star}{clip(draft.steps[sid].get('text', ''), 26)} ({sid})"

    def currencies(self) -> List[str]:
        return [c for c in (self.funnel.payments.currency_of(m) for m in self.funnel.payments.configured()) if c]

    async def builder_input(self, inc: Incoming) -> bool:
        state = self.get_bw(inc.user_id)
        if not state:
            return False
        if inc.text.startswith("/"):
            return False
        here = Incoming(user_id=inc.user_id, chat_id=inc.chat_id)
        handler = getattr(self, f"input_{state['kind']}", None)
        if handler is None:
            return False
        return bool(await handler(here, inc, state))

    async def on_admin_input(self, inc: Incoming) -> bool:
        if await self.builder_input(inc):
            return True
        return await super().on_admin_input(inc)

    async def panel_w(self, inc: Incoming, rest: List[str]) -> None:
        draft = self.raw()
        text = self.o("w_home", steps=len(draft.steps), products=len(draft.products),
                      start=draft.start or "-", language=self.funnel.bot.language)
        keyboard = [
            [Btn(self.o("w_steps"), data="ad:ws", style="primary"), Btn(self.o("w_products"), data="ad:wp", style="primary")],
            [Btn(self.o("w_payments"), data="ad:wm"), Btn(self.o("w_view"), data="ad:wv")],
            [Btn(self.o("back_panel"), data="ad:m")],
        ]
        await self.screen(inc, text, keyboard)

    async def panel_wv(self, inc: Incoming, rest: List[str]) -> None:
        self.touch(inc)
        await self.enter_step(inc.user_id, inc.chat_id, self.funnel.start, reset=True)

    async def panel_ws(self, inc: Incoming, rest: List[str]) -> None:
        draft = self.raw()
        rows: Keyboard = [[Btn(self.step_label(draft, sid), data=f"ad:wt:{sid}")] for sid in list(draft.steps)[:MAX_LIST]]
        rows.append([Btn(self.o("w_new_step"), data="ad:wn", style="success")])
        rows.append([Btn(self.o("back"), data="ad:w")])
        await self.screen(inc, self.o("w_steps_text"), rows)

    async def panel_wn(self, inc: Incoming, rest: List[str]) -> None:
        self.set_bw(inc.user_id, "newstep")
        await self.screen(inc, self.o("w_ask_step_text"), self.cancel_to("ad:ws"))

    async def input_newstep(self, here: Incoming, inc: Incoming, state: Dict[str, Any]) -> bool:
        if not inc.text.strip():
            return False
        self.clear_wait(inc.user_id)
        ok, sid = await self.edit_funnel(here, lambda d: d.add_step(inc.text.strip()))
        if ok:
            await self.step_screen(here, sid)
        return True

    async def step_screen(self, inc: Incoming, sid: str) -> None:
        draft = self.raw()
        if sid not in draft.steps:
            await self.screen(inc, self.o("w_no_step"), self.back_to("ad:ws"))
            return
        step = draft.steps[sid]
        lines = [self.o("w_step_title", id=sid, start=self.o("w_start_mark") if sid == draft.start else ""),
                 self.o("w_step_text", text=clip(step.get("text", ""), 300)),
                 self.o("w_step_image", state=self.o("yes" if step.get("image") else "no"))]
        for number, (_, _, button) in enumerate(draft.buttons_of(sid), start=1):
            lines.append(self.o("w_step_button", n=number, text=button.get("text", ""), what=self.describe_button(draft, button)))
        for nudge in step.get("nudges") or []:
            lines.append(self.o("w_step_nudge", after=nudge.get("after"), text=clip(nudge.get("text", ""), 60)))
        ask = step.get("ask")
        if isinstance(ask, dict):
            lines.append(self.o("w_step_ask", answer=ask.get("key"), kind=ask.get("type"), next=step.get("next", "-")))
        keyboard: Keyboard = [
            [Btn(self.o("w_b_text"), data=f"ad:we:{sid}"), Btn(self.o("w_b_image"), data=f"ad:wi:{sid}")],
            [Btn(self.o("w_b_addbtn"), data=f"ad:wb:{sid}", style="success"), Btn(self.o("w_b_delbtn"), data=f"ad:wd:{sid}")],
            [Btn(self.o("w_b_nudge"), data=f"ad:wr:{sid}"), Btn(self.o("w_b_ask"), data=f"ad:wq:{sid}")],
        ]
        if sid != draft.start:
            keyboard.append([Btn(self.o("w_b_start"), data=f"ad:wa:{sid}"), Btn(self.o("w_b_delete"), data=f"ad:wz:{sid}", style="danger")])
        keyboard.append([Btn(self.o("back"), data="ad:ws")])
        await self.screen(inc, "\n".join(lines), keyboard)

    def describe_button(self, draft: Draft, button: Dict[str, Any]) -> str:
        color = COLOR_EMOJI.get(button.get("style", ""), "")
        if "goto" in button:
            what = self.o("w_do_goto", step=button["goto"])
        elif "pay" in button:
            title = draft.products.get(button["pay"], {}).get("title", button["pay"])
            what = self.o("w_do_pay", product=title)
        elif "url" in button:
            what = self.o("w_do_url", url=button["url"])
        elif "manager" in button:
            what = self.o("w_do_manager")
        elif "back" in button:
            what = self.o("w_do_back")
        elif "home" in button:
            what = self.o("w_do_home")
        else:
            what = "?"
        return f"{color} {what}".strip()

    async def panel_wt(self, inc: Incoming, rest: List[str]) -> None:
        await self.step_screen(inc, rest[0] if rest else "")

    async def panel_we(self, inc: Incoming, rest: List[str]) -> None:
        self.set_bw(inc.user_id, "steptext", sid=rest[0])
        await self.screen(inc, self.o("w_ask_step_text"), self.cancel_to(f"ad:wt:{rest[0]}"))

    async def input_steptext(self, here: Incoming, inc: Incoming, state: Dict[str, Any]) -> bool:
        if not inc.text.strip():
            return False
        self.clear_wait(inc.user_id)
        ok, _ = await self.edit_funnel(here, lambda d: d.set_text(state["sid"], inc.text.strip()))
        if ok:
            await self.step_screen(here, state["sid"])
        return True

    async def panel_wi(self, inc: Incoming, rest: List[str]) -> None:
        self.set_bw(inc.user_id, "stepimage", sid=rest[0])
        keyboard = [[Btn(self.o("w_remove_image"), data=f"ad:wix:{rest[0]}")], *self.cancel_to(f"ad:wt:{rest[0]}")]
        await self.screen(inc, self.o("w_ask_image"), keyboard)

    async def panel_wix(self, inc: Incoming, rest: List[str]) -> None:
        ok, _ = await self.edit_funnel(inc, lambda d: d.set_image(rest[0], None))
        if ok:
            await self.step_screen(inc, rest[0])

    async def input_stepimage(self, here: Incoming, inc: Incoming, state: Dict[str, Any]) -> bool:
        if inc.file_kind != "photo" or not inc.file_id:
            await self.screen(here, self.o("w_need_photo"), self.cancel_to(f"ad:wt:{state['sid']}"))
            return True
        self.clear_wait(inc.user_id)
        ok, _ = await self.edit_funnel(here, lambda d: d.set_image(state["sid"], f"file_id:{inc.file_id}"))
        if ok:
            await self.step_screen(here, state["sid"])
        return True

    async def panel_wb(self, inc: Incoming, rest: List[str]) -> None:
        sid = rest[0]
        if self.raw().steps.get(sid, {}).get("ask"):
            await self.screen(inc, self.o("w_question_no_buttons"), self.back_to(f"ad:wt:{sid}"))
            return
        keyboard: Keyboard = [
            [Btn(self.o("w_t_goto"), data=f"ad:wbg:{sid}"), Btn(self.o("w_t_pay"), data=f"ad:wbp:{sid}")],
            [Btn(self.o("w_t_url"), data=f"ad:wbu:{sid}")],
        ]
        if self.funnel.bot.manager_chat is not None:
            keyboard[1].append(Btn(self.o("w_t_manager"), data=f"ad:wbm:{sid}"))
        keyboard.append([Btn(self.o("w_t_back"), data=f"ad:wbk:{sid}:back"), Btn(self.o("w_t_home"), data=f"ad:wbk:{sid}:home")])
        keyboard.append([Btn(self.o("back"), data=f"ad:wt:{sid}")])
        await self.screen(inc, self.o("w_choose_type"), keyboard)

    async def panel_wbg(self, inc: Incoming, rest: List[str]) -> None:
        sid = rest[0]
        draft = self.raw()
        rows = [[Btn(self.step_label(draft, t), data=f"ad:wbG:{sid}:{t}")] for t in list(draft.steps)[:MAX_LIST] if t != sid]
        rows.insert(0, [Btn(self.o("w_new_step"), data=f"ad:wbN:{sid}", style="success")])
        rows.append([Btn(self.o("back"), data=f"ad:wb:{sid}")])
        await self.screen(inc, self.o("w_choose_target"), rows)

    async def panel_wbG(self, inc: Incoming, rest: List[str]) -> None:
        self.set_pending(inc.user_id, sid=rest[0], action="goto", value=rest[1])
        await self.ask_button_text(inc, rest[0])

    async def panel_wbN(self, inc: Incoming, rest: List[str]) -> None:
        self.set_bw(inc.user_id, "buttonstep", sid=rest[0])
        await self.screen(inc, self.o("w_ask_step_text"), self.cancel_to(f"ad:wt:{rest[0]}"))

    async def input_buttonstep(self, here: Incoming, inc: Incoming, state: Dict[str, Any]) -> bool:
        if not inc.text.strip():
            return False
        ok, target = await self.edit_funnel(here, lambda d: d.add_step(inc.text.strip()))
        if not ok:
            self.clear_wait(inc.user_id)
            return True
        self.set_pending(inc.user_id, sid=state["sid"], action="goto", value=target)
        await self.ask_button_text(here, state["sid"])
        return True

    async def panel_wbp(self, inc: Incoming, rest: List[str]) -> None:
        sid = rest[0]
        draft = self.raw()
        if not draft.products:
            await self.screen(inc, self.o("w_no_products"), self.back_to(f"ad:wb:{sid}"))
            return
        rows = [[Btn(clip(p.get("title", pid), 30), data=f"ad:wbP:{sid}:{pid}")] for pid, p in draft.products.items()]
        rows.append([Btn(self.o("back"), data=f"ad:wb:{sid}")])
        await self.screen(inc, self.o("w_choose_product"), rows)

    async def panel_wbP(self, inc: Incoming, rest: List[str]) -> None:
        self.set_pending(inc.user_id, sid=rest[0], action="pay", value=rest[1])
        await self.ask_button_text(inc, rest[0])

    async def panel_wbu(self, inc: Incoming, rest: List[str]) -> None:
        self.set_bw(inc.user_id, "buttonurl", sid=rest[0])
        await self.screen(inc, self.o("w_ask_url"), self.cancel_to(f"ad:wt:{rest[0]}"))

    async def input_buttonurl(self, here: Incoming, inc: Incoming, state: Dict[str, Any]) -> bool:
        url = inc.text.strip()
        if not url.startswith(("http://", "https://")):
            await self.screen(here, self.o("w_bad_url"), self.cancel_to(f"ad:wt:{state['sid']}"))
            return True
        self.set_pending(inc.user_id, sid=state["sid"], action="url", value=url)
        await self.ask_button_text(here, state["sid"])
        return True

    async def panel_wbm(self, inc: Incoming, rest: List[str]) -> None:
        self.set_pending(inc.user_id, sid=rest[0], action="manager", value=True)
        await self.ask_button_text(inc, rest[0])

    async def panel_wbk(self, inc: Incoming, rest: List[str]) -> None:
        sid, kind = rest[0], rest[1]
        text = self.tx("back") if kind == "back" else self.tx("home")
        ok, _ = await self.edit_funnel(inc, lambda d: d.add_button(sid, button_dict(text, kind, True, "plain")))
        if ok:
            await self.step_screen(inc, sid)

    async def ask_button_text(self, inc: Incoming, sid: str) -> None:
        self.set_bw(inc.user_id, "buttontext", sid=sid)
        await self.screen(inc, self.o("w_ask_button_text"), self.cancel_to(f"ad:wt:{sid}"))

    async def input_buttontext(self, here: Incoming, inc: Incoming, state: Dict[str, Any]) -> bool:
        text = inc.text.strip()
        if not text:
            return False
        pending = self.get_pending(inc.user_id)
        if not pending:
            self.clear_wait(inc.user_id)
            return False
        pending["text"] = text[:60]
        self.set_pending(inc.user_id, **pending)
        self.clear_wait(inc.user_id)
        sid = pending["sid"]
        keyboard = [
            [Btn(self.o("w_c_blue"), data=f"ad:wbc:{sid}:blue", style="primary"), Btn(self.o("w_c_green"), data=f"ad:wbc:{sid}:green", style="success")],
            [Btn(self.o("w_c_red"), data=f"ad:wbc:{sid}:red", style="danger"), Btn(self.o("w_c_plain"), data=f"ad:wbc:{sid}:plain")],
        ]
        await self.screen(here, self.o("w_choose_color"), keyboard)
        return True

    async def panel_wbc(self, inc: Incoming, rest: List[str]) -> None:
        sid, color = rest[0], rest[1]
        pending = self.get_pending(inc.user_id)
        if not pending or color not in STYLES or pending.get("sid") != sid:
            await self.screen(inc, self.o("w_draft_gone"), self.back_to(f"ad:wt:{sid}"))
            return
        self.drop_pending(inc.user_id)
        ok, _ = await self.edit_funnel(
            inc, lambda d: d.add_button(sid, button_dict(pending["text"], pending["action"], pending["value"], color)))
        if ok:
            await self.step_screen(inc, sid)

    async def panel_wd(self, inc: Incoming, rest: List[str]) -> None:
        sid = rest[0]
        draft = self.raw()
        rows = [[Btn(f"🗑 {clip(b.get('text', ''), 30)}", data=f"ad:wdx:{sid}:{r}:{i}")] for r, i, b in draft.buttons_of(sid)]
        if not rows:
            await self.screen(inc, self.o("w_no_buttons"), self.back_to(f"ad:wt:{sid}"))
            return
        rows.append([Btn(self.o("back"), data=f"ad:wt:{sid}")])
        await self.screen(inc, self.o("w_choose_delete"), rows)

    async def panel_wdx(self, inc: Incoming, rest: List[str]) -> None:
        sid, r, i = rest[0], int(rest[1]), int(rest[2])
        ok, _ = await self.edit_funnel(inc, lambda d: d.remove_button(sid, r, i))
        if ok:
            await self.step_screen(inc, sid)

    async def panel_wr(self, inc: Incoming, rest: List[str]) -> None:
        sid = rest[0]
        nudges = self.raw().steps.get(sid, {}).get("nudges") or []
        rows: Keyboard = [[Btn(f"🗑 {n.get('after')}: {clip(n.get('text', ''), 24)}", data=f"ad:wrx:{sid}:{k}")] for k, n in enumerate(nudges)]
        rows.append([Btn(self.o(f"w_d_{code}"), data=f"ad:wrd:{sid}:{code}", style="success") for code in list(DELAYS)[:2]])
        rows.append([Btn(self.o(f"w_d_{code}"), data=f"ad:wrd:{sid}:{code}", style="success") for code in list(DELAYS)[2:]])
        rows.append([Btn(self.o("back"), data=f"ad:wt:{sid}")])
        await self.screen(inc, self.o("w_nudge_menu"), rows)

    async def panel_wrx(self, inc: Incoming, rest: List[str]) -> None:
        sid, index = rest[0], int(rest[1])
        ok, _ = await self.edit_funnel(inc, lambda d: d.remove_nudge(sid, index))
        if ok:
            await self.step_screen(inc, sid)

    async def panel_wrd(self, inc: Incoming, rest: List[str]) -> None:
        self.set_bw(inc.user_id, "nudgetext", sid=rest[0], after=DELAYS[rest[1]])
        await self.screen(inc, self.o("w_ask_nudge_text"), self.cancel_to(f"ad:wt:{rest[0]}"))

    async def input_nudgetext(self, here: Incoming, inc: Incoming, state: Dict[str, Any]) -> bool:
        if not inc.text.strip():
            return False
        self.clear_wait(inc.user_id)
        ok, _ = await self.edit_funnel(here, lambda d: d.add_nudge(state["sid"], state["after"], inc.text.strip()))
        if ok:
            await self.step_screen(here, state["sid"])
        return True

    async def panel_wq(self, inc: Incoming, rest: List[str]) -> None:
        sid = rest[0]
        rows: Keyboard = [
            [Btn(self.o("w_q_text"), data=f"ad:wqt:{sid}:text"), Btn(self.o("w_q_email"), data=f"ad:wqt:{sid}:email")],
            [Btn(self.o("w_q_phone"), data=f"ad:wqt:{sid}:phone"), Btn(self.o("w_q_number"), data=f"ad:wqt:{sid}:number")],
        ]
        if self.raw().steps.get(sid, {}).get("ask"):
            rows.append([Btn(self.o("w_q_remove"), data=f"ad:wqx:{sid}", style="danger")])
        rows.append([Btn(self.o("back"), data=f"ad:wt:{sid}")])
        await self.screen(inc, self.o("w_question_menu"), rows)

    async def panel_wqx(self, inc: Incoming, rest: List[str]) -> None:
        ok, _ = await self.edit_funnel(inc, lambda d: d.clear_question(rest[0]))
        if ok:
            await self.step_screen(inc, rest[0])

    async def panel_wqt(self, inc: Incoming, rest: List[str]) -> None:
        sid, kind = rest[0], rest[1]
        draft = self.raw()
        rows = [[Btn(self.step_label(draft, t), data=f"ad:wqn:{sid}:{kind}:{t}")] for t in list(draft.steps)[:MAX_LIST] if t != sid]
        if not rows:
            await self.screen(inc, self.o("w_need_other_step"), self.back_to(f"ad:wt:{sid}"))
            return
        rows.append([Btn(self.o("back"), data=f"ad:wq:{sid}")])
        await self.screen(inc, self.o("w_question_next"), rows)

    async def panel_wqn(self, inc: Incoming, rest: List[str]) -> None:
        sid, kind, target = rest[0], rest[1], rest[2]
        if kind not in ASK_KEYS:
            return
        ok, _ = await self.edit_funnel(inc, lambda d: d.set_question(sid, kind, target))
        if ok:
            await self.step_screen(inc, sid)

    async def panel_wa(self, inc: Incoming, rest: List[str]) -> None:
        ok, _ = await self.edit_funnel(inc, lambda d: d.set_start(rest[0]))
        if ok:
            await self.step_screen(inc, rest[0])

    async def panel_wz(self, inc: Incoming, rest: List[str]) -> None:
        keyboard = [[Btn(self.o("w_yes_delete"), data=f"ad:wzy:{rest[0]}", style="danger"), Btn(self.o("no_btn"), data=f"ad:wt:{rest[0]}")]]
        await self.screen(inc, self.o("w_confirm_delete_step"), keyboard)

    async def panel_wzy(self, inc: Incoming, rest: List[str]) -> None:
        ok, _ = await self.edit_funnel(inc, lambda d: d.remove_step(rest[0]))
        if ok:
            await self.panel_ws(inc, [])

    def product_text(self, draft: Draft, pid: str) -> str:
        product = draft.products[pid]
        lines = [self.o("w_prod_title", title=product.get("title", pid), id=pid)]
        if product.get("description"):
            lines.append(self.o("w_prod_desc", text=clip(product["description"], 200)))
        prices = ", ".join(format_amount(_dec(v), c) for c, v in (product.get("prices") or {}).items())
        lines.append(self.o("w_prod_prices", prices=prices or "-"))
        for item in product.get("access") or []:
            lines.append(self.o("w_prod_access", what=self.describe_access(item)))
        if not product.get("access"):
            lines.append(self.o("w_prod_no_access"))
        return "\n".join(lines)

    def describe_access(self, item: Dict[str, Any]) -> str:
        if "channel" in item:
            body = item["channel"]
            days = body.get("days")
            return self.o("w_acc_channel", chat=body.get("chat"), days=self.o("w_days", n=days) if days else self.o("w_forever"))
        if "message" in item:
            body = item["message"]
            return self.o("w_acc_message", text=clip(body.get("text", ""), 40), files=len(body.get("files") or []))
        return self.o("w_acc_manager")

    async def panel_wp(self, inc: Incoming, rest: List[str]) -> None:
        draft = self.raw()
        rows: Keyboard = [[Btn(clip(p.get("title", pid), 30), data=f"ad:wpt:{pid}")] for pid, p in list(draft.products.items())[:MAX_LIST]]
        rows.append([Btn(self.o("w_new_product"), data="ad:wpn", style="success")])
        rows.append([Btn(self.o("back"), data="ad:w")])
        await self.screen(inc, self.o("w_products_text"), rows)

    async def product_screen(self, inc: Incoming, pid: str) -> None:
        draft = self.raw()
        if pid not in draft.products:
            await self.screen(inc, self.o("w_no_product"), self.back_to("ad:wp"))
            return
        keyboard: Keyboard = [
            [Btn(self.o("w_p_title"), data=f"ad:wpe:{pid}:title"), Btn(self.o("w_p_desc"), data=f"ad:wpe:{pid}:description")],
            [Btn(self.o("w_p_prices"), data=f"ad:wpc:{pid}"), Btn(self.o("w_p_addaccess"), data=f"ad:wpa:{pid}", style="success")],
            [Btn(self.o("w_p_delaccess"), data=f"ad:wpx:{pid}"), Btn(self.o("w_p_delete"), data=f"ad:wpz:{pid}", style="danger")],
            [Btn(self.o("back"), data="ad:wp")],
        ]
        await self.screen(inc, self.product_text(draft, pid), keyboard)

    async def panel_wpt(self, inc: Incoming, rest: List[str]) -> None:
        await self.product_screen(inc, rest[0] if rest else "")

    async def panel_wpn(self, inc: Incoming, rest: List[str]) -> None:
        if not self.currencies():
            await self.screen(inc, self.o("w_no_currency"), self.back_to("ad:wm"))
            return
        self.set_bw(inc.user_id, "prodtitle")
        await self.screen(inc, self.o("w_ask_product_title"), self.cancel_to("ad:wp"))

    async def input_prodtitle(self, here: Incoming, inc: Incoming, state: Dict[str, Any]) -> bool:
        if not inc.text.strip():
            return False
        self.set_pending(inc.user_id, title=inc.text.strip()[:60])
        self.set_bw(inc.user_id, "proddesc")
        keyboard = [[Btn(self.o("w_skip"), data="ad:wps")], *self.cancel_to("ad:wp")]
        await self.screen(here, self.o("w_ask_product_desc"), keyboard)
        return True

    async def panel_wps(self, inc: Incoming, rest: List[str]) -> None:
        await self.ask_price(inc, self.get_pending(inc.user_id).get("title", ""), "")

    async def input_proddesc(self, here: Incoming, inc: Incoming, state: Dict[str, Any]) -> bool:
        if not inc.text.strip():
            return False
        await self.ask_price(here, self.get_pending(inc.user_id).get("title", ""), inc.text.strip()[:500])
        return True

    async def ask_price(self, inc: Incoming, title: str, description: str) -> None:
        currency = self.currencies()[0]
        self.set_pending(inc.user_id, title=title, description=description, currency=currency)
        self.set_bw(inc.user_id, "prodprice")
        await self.screen(inc, self.o("w_ask_price", currency=currency), self.cancel_to("ad:wp"))

    def parse_price(self, text: str, currency: str) -> Optional[Any]:
        try:
            value = float(text.strip().replace(",", "."))
        except ValueError:
            return None
        if value <= 0:
            return None
        if currency == STARS:
            return int(value) if value == int(value) else None
        return int(value) if value == int(value) else round(value, 2)

    async def input_prodprice(self, here: Incoming, inc: Incoming, state: Dict[str, Any]) -> bool:
        pending = self.get_pending(inc.user_id)
        value = self.parse_price(inc.text, pending.get("currency", ""))
        if value is None:
            await self.screen(here, self.o("w_bad_price"), self.cancel_to("ad:wp"))
            return True
        self.clear_wait(inc.user_id)
        self.drop_pending(inc.user_id)
        ok, pid = await self.edit_funnel(
            here, lambda d: d.add_product(pending["title"], pending.get("description", ""), {pending["currency"]: value}))
        if ok:
            await self.plain(here.chat_id, self.o("w_product_hint"))
            await self.product_screen(here, pid)
        return True

    async def panel_wpe(self, inc: Incoming, rest: List[str]) -> None:
        self.set_bw(inc.user_id, "prodfield", pid=rest[0], field=rest[1])
        await self.screen(inc, self.o("w_ask_product_title" if rest[1] == "title" else "w_ask_product_desc"), self.cancel_to(f"ad:wpt:{rest[0]}"))

    async def input_prodfield(self, here: Incoming, inc: Incoming, state: Dict[str, Any]) -> bool:
        if not inc.text.strip():
            return False
        self.clear_wait(inc.user_id)

        def action(d: Draft) -> None:
            d.product(state["pid"])[state["field"]] = inc.text.strip()[:500]

        ok, _ = await self.edit_funnel(here, action)
        if ok:
            await self.product_screen(here, state["pid"])
        return True

    async def panel_wpc(self, inc: Incoming, rest: List[str]) -> None:
        pid = rest[0]
        prices = self.raw().products.get(pid, {}).get("prices") or {}
        rows: Keyboard = []
        for currency in self.currencies():
            label = f"{currency}: {format_amount(_dec(prices[currency]), currency)}" if currency in prices else f"{currency}: +"
            rows.append([Btn(label, data=f"ad:wpv:{pid}:{currency}")])
        for currency in prices:
            if len(prices) > 1:
                rows.append([Btn(self.o("w_remove_price", currency=currency), data=f"ad:wpr:{pid}:{currency}")])
        rows.append([Btn(self.o("back"), data=f"ad:wpt:{pid}")])
        await self.screen(inc, self.o("w_prices_menu"), rows)

    async def panel_wpv(self, inc: Incoming, rest: List[str]) -> None:
        self.set_bw(inc.user_id, "setprice", pid=rest[0], currency=rest[1])
        await self.screen(inc, self.o("w_ask_price", currency=rest[1]), self.cancel_to(f"ad:wpc:{rest[0]}"))

    async def input_setprice(self, here: Incoming, inc: Incoming, state: Dict[str, Any]) -> bool:
        value = self.parse_price(inc.text, state["currency"])
        if value is None:
            await self.screen(here, self.o("w_bad_price"), self.cancel_to(f"ad:wpc:{state['pid']}"))
            return True
        self.clear_wait(inc.user_id)
        ok, _ = await self.edit_funnel(here, lambda d: d.set_price(state["pid"], state["currency"], value))
        if ok:
            await self.product_screen(here, state["pid"])
        return True

    async def panel_wpr(self, inc: Incoming, rest: List[str]) -> None:
        ok, _ = await self.edit_funnel(inc, lambda d: d.remove_price(rest[0], rest[1]))
        if ok:
            await self.product_screen(inc, rest[0])

    async def panel_wpa(self, inc: Incoming, rest: List[str]) -> None:
        pid = rest[0]
        rows: Keyboard = [
            [Btn(self.o("w_a_channel"), data=f"ad:wpac:{pid}")],
            [Btn(self.o("w_a_message"), data=f"ad:wpam:{pid}")],
        ]
        if self.funnel.bot.manager_chat is not None:
            rows.append([Btn(self.o("w_a_manager"), data=f"ad:wpag:{pid}")])
        rows.append([Btn(self.o("back"), data=f"ad:wpt:{pid}")])
        await self.screen(inc, self.o("w_access_menu"), rows)

    async def panel_wpac(self, inc: Incoming, rest: List[str]) -> None:
        self.set_bw(inc.user_id, "accchat", pid=rest[0])
        await self.screen(inc, self.o("w_ask_channel"), self.cancel_to(f"ad:wpt:{rest[0]}"))

    async def input_accchat(self, here: Incoming, inc: Incoming, state: Dict[str, Any]) -> bool:
        text = inc.text.strip()
        if not text.lstrip("-").isdigit():
            await self.screen(here, self.o("w_bad_channel"), self.cancel_to(f"ad:wpt:{state['pid']}"))
            return True
        chat = int(text)
        self.clear_wait(inc.user_id)
        problem = ""
        try:
            problem = await self.transport.chat_status(chat)
        except (TransportError, NotImplementedError):
            problem = ""
        rows: Keyboard = [[Btn(self.o("w_days", n=label), data=f"ad:wpad:{state['pid']}:{chat}:{days}") for label, days in DAYS[:2]],
                          [Btn(self.o("w_days", n=label), data=f"ad:wpad:{state['pid']}:{chat}:{days}") for label, days in DAYS[2:]],
                          [Btn(self.o("w_forever"), data=f"ad:wpad:{state['pid']}:{chat}:0")]]
        note = self.o("w_channel_problem", problem=problem) + "\n\n" if problem else ""
        await self.screen(here, note + self.o("w_choose_days"), rows)
        return True

    async def panel_wpad(self, inc: Incoming, rest: List[str]) -> None:
        pid, chat, days = rest[0], int(rest[1]), int(rest[2])
        ok, _ = await self.edit_funnel(inc, lambda d: d.add_access(pid, channel_item(chat, days or None)))
        if ok:
            await self.product_screen(inc, pid)

    async def panel_wpam(self, inc: Incoming, rest: List[str]) -> None:
        self.set_bw(inc.user_id, "accmsg", pid=rest[0])
        await self.screen(inc, self.o("w_ask_message"), self.cancel_to(f"ad:wpt:{rest[0]}"))

    async def input_accmsg(self, here: Incoming, inc: Incoming, state: Dict[str, Any]) -> bool:
        if not inc.text.strip():
            return False
        self.set_pending(inc.user_id, pid=state["pid"], text=inc.text.strip())
        self.set_bw(inc.user_id, "accfile", pid=state["pid"])
        keyboard = [[Btn(self.o("w_no_file"), data=f"ad:wpaf:{state['pid']}")], *self.cancel_to(f"ad:wpt:{state['pid']}")]
        await self.screen(here, self.o("w_ask_file"), keyboard)
        return True

    async def input_accfile(self, here: Incoming, inc: Incoming, state: Dict[str, Any]) -> bool:
        if inc.file_kind != "document" or not inc.file_id:
            await self.screen(here, self.o("w_need_document"), self.cancel_to(f"ad:wpt:{state['pid']}"))
            return True
        return await self.finish_message(here, inc.user_id, state["pid"], f"file_id:{inc.file_id}")

    async def panel_wpaf(self, inc: Incoming, rest: List[str]) -> None:
        await self.finish_message(inc, inc.user_id, rest[0], None)

    async def finish_message(self, here: Incoming, user_id: int, pid: str, file_ref: Optional[str]) -> bool:
        pending = self.get_pending(user_id)
        self.clear_wait(user_id)
        self.drop_pending(user_id)
        ok, _ = await self.edit_funnel(here, lambda d: d.add_access(pid, message_item(pending.get("text", ""), file_ref)))
        if ok:
            await self.product_screen(here, pid)
        return True

    async def panel_wpag(self, inc: Incoming, rest: List[str]) -> None:
        self.set_bw(inc.user_id, "accmanager", pid=rest[0])
        await self.screen(inc, self.o("w_ask_manager_text"), self.cancel_to(f"ad:wpt:{rest[0]}"))

    async def input_accmanager(self, here: Incoming, inc: Incoming, state: Dict[str, Any]) -> bool:
        if not inc.text.strip():
            return False
        self.clear_wait(inc.user_id)
        ok, _ = await self.edit_funnel(here, lambda d: d.add_access(state["pid"], {"manager": {"text": inc.text.strip()}}))
        if ok:
            await self.product_screen(here, state["pid"])
        return True

    async def panel_wpx(self, inc: Incoming, rest: List[str]) -> None:
        pid = rest[0]
        items = self.raw().products.get(pid, {}).get("access") or []
        if not items:
            await self.screen(inc, self.o("w_no_access"), self.back_to(f"ad:wpt:{pid}"))
            return
        rows = [[Btn(f"🗑 {self.describe_access(item)}", data=f"ad:wpxx:{pid}:{k}")] for k, item in enumerate(items)]
        rows.append([Btn(self.o("back"), data=f"ad:wpt:{pid}")])
        await self.screen(inc, self.o("w_choose_delete"), rows)

    async def panel_wpxx(self, inc: Incoming, rest: List[str]) -> None:
        ok, _ = await self.edit_funnel(inc, lambda d: d.remove_access(rest[0], int(rest[1])))
        if ok:
            await self.product_screen(inc, rest[0])

    async def panel_wpz(self, inc: Incoming, rest: List[str]) -> None:
        keyboard = [[Btn(self.o("w_yes_delete"), data=f"ad:wpzy:{rest[0]}", style="danger"), Btn(self.o("no_btn"), data=f"ad:wpt:{rest[0]}")]]
        await self.screen(inc, self.o("w_confirm_delete_product"), keyboard)

    async def panel_wpzy(self, inc: Incoming, rest: List[str]) -> None:
        ok, _ = await self.edit_funnel(inc, lambda d: d.remove_product(rest[0]))
        if ok:
            await self.panel_wp(inc, [])

    async def panel_wm(self, inc: Incoming, rest: List[str]) -> None:
        pay = self.funnel.payments
        lines = [self.o("w_pay_title")]
        for method in ("stars", "telegram", "yookassa", "crypto", "manual"):
            currency = pay.currency_of(method)
            lines.append(self.o("w_pay_on" if currency else "w_pay_off", method=self.o(f"w_method_{method}"), currency=currency or ""))
        lines.append(self.o("w_manager_state", state=self.funnel.bot.manager_chat if self.funnel.bot.manager_chat is not None else self.o("no")))
        lines.append(self.o("w_pay_more"))
        lines.append(self.o("w_pay_test", state=self.o("yes" if self.funnel.bot.test_mode else "no")))
        lines.append(self.o("w_pay_language", language=self.funnel.bot.language))
        keyboard: Keyboard = [
            [Btn(self.o("w_stars_off" if pay.stars else "w_stars_on"), data="ad:wj")],
            [Btn(self.o("w_test_off" if self.funnel.bot.test_mode else "w_test_on"), data="ad:wk")],
            [Btn(self.o("w_switch_language"), data="ad:wl")],
            [Btn(self.o("back"), data="ad:w")],
        ]
        await self.screen(inc, "\n".join(lines), keyboard)

    async def cmd_managerchat(self, inc: Incoming, args: List[str]) -> None:
        here = Incoming(user_id=inc.user_id, chat_id=inc.chat_id)
        ok, _ = await self.edit_funnel(here, lambda d: d.set_manager_chat(inc.chat_id))
        if ok:
            await self.screen(here, self.o("w_manager_set"))

    async def panel_wj(self, inc: Incoming, rest: List[str]) -> None:
        on = not self.funnel.payments.stars
        ok, _ = await self.edit_funnel(inc, lambda d: d.set_stars(on))
        if ok:
            await self.panel_wm(inc, [])

    async def panel_wk(self, inc: Incoming, rest: List[str]) -> None:
        on = not self.funnel.bot.test_mode
        ok, _ = await self.edit_funnel(inc, lambda d: d.set_test_mode(on))
        if ok:
            await self.panel_wm(inc, [])

    async def panel_wl(self, inc: Incoming, rest: List[str]) -> None:
        language = "en" if self.funnel.bot.language == "ru" else "ru"
        ok, _ = await self.edit_funnel(inc, lambda d: d.set_language(language))
        if ok:
            await self.panel_wm(inc, [])


def _dec(value: Any) -> Any:
    from decimal import Decimal

    return Decimal(str(value))
