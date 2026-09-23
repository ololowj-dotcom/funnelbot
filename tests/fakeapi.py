import asyncio
import time

from aiohttp import web

BOT = {"id": 900, "is_bot": True, "first_name": "Funnel", "username": "funnel_test_bot"}


def user(uid, first="User", username=None):
    data = {"id": uid, "is_bot": False, "first_name": first}
    if username:
        data["username"] = username
    return data


class FakeTelegram:
    def __init__(self):
        self.calls = []
        self.updates = []
        self.update_id = 0
        self.message_id = 1000
        self.runner = None
        self.url = ""
        self.fail = {}
        self.bot_status = "administrator"
        self.rights = {}

    async def start(self):
        app = web.Application()
        app.router.add_route("*", "/bot{token}/{method}", self.handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = self.runner.addresses[0][1]
        self.url = f"http://127.0.0.1:{port}"

    async def stop(self):
        await self.runner.cleanup()

    def named(self, method):
        return [params for name, params in self.calls if name == method]

    def push(self, payload):
        self.update_id += 1
        payload = dict(payload)
        payload["update_id"] = self.update_id
        self.updates.append(payload)

    def message(self, uid, text, chat=None, **extra):
        self.message_id += 1
        message = {"message_id": self.message_id, "date": int(time.time()), "chat": {"id": chat or uid, "type": "private"},
                   "from": user(uid), "text": text}
        if text.startswith("/"):
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        message.update(extra)
        self.push({"message": message})

    def press(self, uid, data, message_id):
        self.push({"callback_query": {
            "id": f"cq{self.update_id + 1}", "from": user(uid), "chat_instance": "ci", "data": data,
            "message": {"message_id": message_id, "date": int(time.time()), "chat": {"id": uid, "type": "private"},
                        "from": BOT, "text": "x"},
        }})

    def pre_checkout(self, uid, payload, currency, total):
        self.push({"pre_checkout_query": {"id": f"pq{self.update_id + 1}", "from": user(uid), "currency": currency,
                                          "total_amount": total, "invoice_payload": payload}})

    def paid(self, uid, payload, currency, total, charge):
        self.message(uid, None or "", successful_payment={
            "currency": currency, "total_amount": total, "invoice_payload": payload,
            "telegram_payment_charge_id": charge, "provider_payment_charge_id": ""})

    def join_request(self, chat, uid):
        self.push({"chat_join_request": {"chat": {"id": chat, "type": "channel", "title": "C"}, "from": user(uid),
                                         "user_chat_id": uid, "date": int(time.time())}})

    def sent_message(self, params):
        self.message_id += 1
        return {"message_id": self.message_id, "date": int(time.time()),
                "chat": {"id": int(params.get("chat_id", 0)), "type": "private"}, "from": BOT,
                "text": params.get("text", "")}

    async def handle(self, request):
        method = request.match_info["method"]
        params = dict(await request.post()) if request.method == "POST" else dict(request.query)
        params = {k: (v if isinstance(v, str) else "<file>") for k, v in params.items()}
        if method != "getUpdates":
            self.calls.append((method, params))
        if method in self.fail:
            return web.json_response({"ok": False, "error_code": 400, "description": self.fail[method]}, status=400)
        if method == "getUpdates":
            offset = int(params.get("offset", 0) or 0)
            ready = [u for u in self.updates if u["update_id"] >= offset]
            if not ready:
                await asyncio.sleep(0.05)
            return web.json_response({"ok": True, "result": ready})
        result = self.result(method, params)
        return web.json_response({"ok": True, "result": result})

    def result(self, method, params):
        if method == "getMe":
            return BOT
        if method in ("sendMessage", "sendInvoice", "sendPhoto"):
            return self.sent_message(params)
        if method == "sendDocument":
            message = self.sent_message(params)
            message["document"] = {"file_id": "DOCFILE", "file_unique_id": "u"}
            return message
        if method == "editMessageText":
            return self.sent_message(params)
        if method == "copyMessage":
            self.message_id += 1
            return {"message_id": self.message_id}
        if method == "createChatInviteLink":
            return {"invite_link": "https://t.me/+FAKELINK", "creator": BOT, "creates_join_request": True,
                    "is_primary": False, "is_revoked": False}
        if method == "getChat":
            return {"id": int(params.get("chat_id", 0)), "type": "channel", "title": "Club", "accent_color_id": 0,
                    "max_reaction_count": 0,
                    "accepted_gift_types": {"unlimited_gifts": False, "limited_gifts": False, "unique_gifts": False,
                                            "premium_subscription": False, "gifts_from_channels": False}}
        if method == "getChatMember":
            uid = int(params.get("user_id", 0))
            if uid == BOT["id"] and self.bot_status != "administrator":
                return {"status": self.bot_status, "user": BOT}
            if uid == BOT["id"]:
                rights = {k: True for k in (
                    "can_be_edited", "is_anonymous", "can_manage_chat", "can_delete_messages", "can_manage_video_chats",
                    "can_restrict_members", "can_promote_members", "can_change_info", "can_invite_users",
                    "can_post_stories", "can_edit_stories", "can_delete_stories", "can_send_welcome_messages")}
                rights.update(self.rights)
                return {"status": self.bot_status, "user": BOT, **rights}
            return {"status": "left", "user": user(uid)}
        return True
