from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import (
    AiogramError,
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BufferedInputFile,
    CallbackQuery,
    ChatJoinRequest,
    ChatMemberUpdated,
    CopyTextButton,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from .engine import Engine
from .loader import load_funnel
from .providers import CryptoPayProvider, Provider, YooKassaProvider
from .schema import Funnel
from .store import Store
from .transport import Blocked, Btn, Incoming, Invoice, Keyboard, RetryAfter, Transport, TransportError

CAPTION_LIMIT = 1024
TICK_SECONDS = 5
GONE_MARKERS = ("chat not found", "user is deactivated", "bot was blocked", "user not found", "peer_id_invalid")
ALREADY_DONE_MARKERS = ("user_already_participant", "hide_requester_missing", "already", "not a participant",
                        "participant_id_invalid", "user_not_participant", "user not found")
EDIT_GONE_MARKERS = ("message to edit not found", "message can't be edited", "message is not modified", "there is no text")
COMMANDS_PUBLIC = ("start", "help", "terms", "paysupport", "deleteme", "stop", "resume")
COMMANDS_ADMIN = ("admin", "managerchat", "stats", "leads", "payments", "user", "grant", "revoke", "refund", "erase", "broadcast", "reload")

log = logging.getLogger("funnelbot")


def media_source(value: str) -> Union[str, FSInputFile]:
    if value.startswith("file_id:"):
        return value[len("file_id:"):]
    if value.startswith(("http://", "https://")):
        return value
    return FSInputFile(value)


def convert_button(button: Btn) -> InlineKeyboardButton:
    fields: Dict[str, Any] = {"text": button.text}
    if button.style:
        fields["style"] = button.style
    if button.icon:
        fields["icon_custom_emoji_id"] = button.icon
    if button.url:
        fields["url"] = button.url
    elif button.copy:
        fields["copy_text"] = CopyTextButton(text=button.copy)
    else:
        fields["callback_data"] = button.data or "noop"
    return InlineKeyboardButton(**fields)


def convert_keyboard(keyboard: Optional[Keyboard]) -> Optional[InlineKeyboardMarkup]:
    if not keyboard:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[convert_button(b) for b in row] for row in keyboard])


class AiogramTransport(Transport):
    def __init__(self, bot: Bot):
        self.bot = bot

    async def call(self, coroutine: Any, user: bool = False) -> Any:
        try:
            return await coroutine
        except TelegramRetryAfter as exc:
            raise RetryAfter(exc.retry_after) from exc
        except TelegramForbiddenError as exc:
            if user:
                raise Blocked(str(exc)) from exc
            raise TransportError(str(exc)) from exc
        except TelegramBadRequest as exc:
            message = str(exc).lower()
            if user and any(marker in message for marker in GONE_MARKERS):
                raise Blocked(str(exc)) from exc
            raise TransportError(str(exc)) from exc
        except TelegramNetworkError as exc:
            raise TransportError(f"network error: {exc}") from exc
        except (TelegramAPIError, AiogramError) as exc:
            raise TransportError(str(exc)) from exc

    async def send(self, chat_id, text, keyboard=None, image=None, parse_mode="HTML"):
        markup = convert_keyboard(keyboard)
        if image:
            photo = media_source(image)
            if len(text) <= CAPTION_LIMIT:
                message = await self.call(self.bot.send_photo(chat_id, photo, caption=text, parse_mode=parse_mode,
                                                              reply_markup=markup), True)
                return message.message_id
            await self.call(self.bot.send_photo(chat_id, photo), True)
        message = await self.call(self.bot.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=markup,
                                                        link_preview_options={"is_disabled": True}), True)
        return message.message_id

    async def edit(self, chat_id, message_id, text, keyboard=None, parse_mode="HTML"):
        try:
            await self.call(self.bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, parse_mode=parse_mode,
                                                       reply_markup=convert_keyboard(keyboard),
                                                       link_preview_options={"is_disabled": True}), True)
            return True
        except TransportError as exc:
            message = str(exc).lower()
            if "message is not modified" in message:
                return True
            if any(marker in message for marker in EDIT_GONE_MARKERS):
                return False
            raise

    async def clear_keyboard(self, chat_id, message_id):
        try:
            await self.call(self.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None))
        except TransportError as exc:
            if "not modified" not in str(exc).lower():
                raise

    async def send_file(self, chat_id, file, caption="", parse_mode="HTML"):
        message = await self.call(self.bot.send_document(chat_id, media_source(file), caption=caption or None,
                                                         parse_mode=parse_mode), True)
        document = getattr(message, "document", None)
        return f"file_id:{document.file_id}" if document else None

    async def send_document_bytes(self, chat_id, name, content, caption=""):
        await self.call(self.bot.send_document(chat_id, BufferedInputFile(content, filename=name),
                                               caption=caption or None), True)

    async def send_invoice(self, chat_id, invoice: Invoice):
        pay = {"text": invoice.pay_text or "Pay", "pay": True}
        if invoice.pay_style:
            pay["style"] = invoice.pay_style
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(**pay)]])
        kwargs: Dict[str, Any] = {}
        if invoice.provider_token:
            kwargs.update(provider_token=invoice.provider_token, need_email=invoice.need_email or None,
                          send_email_to_provider=invoice.send_email_to_provider or None,
                          provider_data=invoice.provider_data)
        message = await self.call(self.bot.send_invoice(
            chat_id, invoice.title, invoice.description, invoice.payload, invoice.currency,
            [LabeledPrice(label=invoice.label, amount=invoice.amount)], reply_markup=markup, **kwargs), True)
        return message.message_id

    async def answer_callback(self, callback_id, text="", alert=False):
        await self.call(self.bot.answer_callback_query(callback_id, text=text or None, show_alert=alert or None))

    async def create_join_link(self, chat, name):
        link = await self.call(self.bot.create_chat_invite_link(chat, name=name, creates_join_request=True))
        return link.invite_link

    async def approve_join(self, chat, user_id):
        try:
            await self.call(self.bot.approve_chat_join_request(chat, user_id))
        except TransportError as exc:
            if not any(marker in str(exc).lower() for marker in ALREADY_DONE_MARKERS):
                raise

    async def decline_join(self, chat, user_id):
        try:
            await self.call(self.bot.decline_chat_join_request(chat, user_id))
        except TransportError as exc:
            if not any(marker in str(exc).lower() for marker in ALREADY_DONE_MARKERS):
                raise

    async def remove_member(self, chat, user_id):
        try:
            await self.call(self.bot.ban_chat_member(chat, user_id))
        except TransportError as exc:
            if not any(marker in str(exc).lower() for marker in ALREADY_DONE_MARKERS):
                raise
            return
        await self.call(self.bot.unban_chat_member(chat, user_id, only_if_banned=True))

    async def refund_stars(self, user_id, charge_id):
        await self.call(self.bot.refund_star_payment(user_id, charge_id))

    async def copy_message(self, to_chat, from_chat, message_id, keyboard=None):
        result = await self.call(self.bot.copy_message(to_chat, from_chat, message_id,
                                                       reply_markup=convert_keyboard(keyboard)), True)
        return result.message_id

    async def chat_status(self, chat):
        return await chat_problem(self.bot, chat)

    async def is_member(self, chat, user_id):
        try:
            member = await self.call(self.bot.get_chat_member(chat, user_id))
        except TransportError:
            return False
        status = getattr(member, "status", "")
        if status in ("creator", "administrator", "member"):
            return True
        return status == "restricted" and bool(getattr(member, "is_member", False))


async def chat_problem(bot: Bot, chat: int) -> str:
    try:
        info = await bot.get_chat(chat)
        me = await bot.get_me()
        member = await bot.get_chat_member(chat, me.id)
    except (TelegramAPIError, AiogramError) as exc:
        return f"the bot cannot see this chat ({exc})"
    title = getattr(info, "title", "") or str(chat)
    status = getattr(member, "status", "")
    if status == "creator":
        return ""
    if status != "administrator":
        return f"the bot is not an administrator of '{title}'"
    missing = [r for r in ("can_invite_users", "can_restrict_members") if not getattr(member, r, False)]
    return f"the bot lacks rights in '{title}': {', '.join(missing)}" if missing else ""


def incoming_from_message(message: Message, payload: str = "") -> Incoming:
    user = message.from_user
    reply = message.reply_to_message
    file_id, file_kind = "", ""
    if message.photo:
        file_id, file_kind = message.photo[-1].file_id, "photo"
    elif message.document:
        file_id, file_kind = message.document.file_id, "document"
    return Incoming(file_id=file_id, file_kind=file_kind,
        user_id=user.id if user else 0, chat_id=message.chat.id, username=(user.username or "") if user else "",
        first_name=(user.first_name or "") if user else "", text=message.text or message.caption or "",
        message_id=message.message_id, payload=payload,
        reply_to=reply.message_id if reply else 0, reply_chat=message.chat.id if reply else 0)


def parse_command(text: str) -> Optional[List[str]]:
    if not text.startswith("/"):
        return None
    head, *args = text.split()
    name = head[1:].split("@")[0].lower()
    return [name, *args] if name else None


def build_router(engine: Engine) -> Router:
    router = Router()

    async def safe(action: Any) -> None:
        try:
            await action
        except Exception:
            log.exception("update handler failed")

    @router.message(F.successful_payment)
    async def paid(message: Message) -> None:
        payment = message.successful_payment
        inc = incoming_from_message(message)
        email = payment.order_info.email if payment.order_info and payment.order_info.email else ""
        await safe(engine.on_successful_payment(
            inc, payment.invoice_payload, payment.telegram_payment_charge_id, payment.currency, payment.total_amount, email or ""))

    @router.pre_checkout_query()
    async def pre_checkout(query: PreCheckoutQuery) -> None:
        try:
            problem = await engine.pre_checkout(query.from_user.id, query.invoice_payload, query.currency, query.total_amount)
        except Exception:
            log.exception("pre-checkout failed")
            problem = "Something went wrong, please try again."
        await query.answer(ok=problem is None, error_message=problem)

    @router.channel_post(F.text.startswith("/id"))
    async def channel_id(post: Message) -> None:
        try:
            await post.answer(engine.o("chat_id_hint", chat=post.chat.id))
        except TelegramAPIError as exc:
            log.warning("could not answer in channel %s: %s", post.chat.id, exc)

    @router.chat_join_request()
    async def join(request: ChatJoinRequest) -> None:
        await safe(engine.on_join_request(request.chat.id, request.from_user.id, request.user_chat_id))

    @router.my_chat_member()
    async def membership(update: ChatMemberUpdated) -> None:
        if update.chat.type != "private":
            return
        status = update.new_chat_member.status
        if engine.store.user(update.chat.id) is None:
            return
        if status in ("kicked", "left"):
            engine.store.update_user(update.chat.id, blocked=1)
        elif status == "member":
            engine.store.update_user(update.chat.id, blocked=0)

    @router.callback_query()
    async def callback(query: CallbackQuery) -> None:
        message = query.message
        if message is None:
            await query.answer()
            return
        has_media = bool(getattr(message, "photo", None) or getattr(message, "video", None)
                         or getattr(message, "document", None) or getattr(message, "animation", None))
        inc = Incoming(
            user_id=query.from_user.id, chat_id=message.chat.id, username=query.from_user.username or "",
            first_name=query.from_user.first_name or "", data=query.data or "", callback_id=query.id,
            message_id=message.message_id, has_media=has_media)
        await safe(engine.on_callback(inc))
        if query.id in engine.answered:
            engine.answered.discard(query.id)
        else:
            try:
                await query.answer()
            except TelegramAPIError:
                pass

    @router.message(~F.text)
    async def media(message: Message) -> None:
        if message.chat.type != "private" or message.from_user is None:
            return
        await safe(engine.on_photo(incoming_from_message(message)))

    @router.message(F.text)
    async def text(message: Message) -> None:
        if message.from_user is None:
            return
        parsed = parse_command(message.text or "")
        inc = incoming_from_message(message)
        if parsed is None:
            if message.chat.type == "private":
                await safe(engine.on_text(inc))
            return
        name, args = parsed[0], parsed[1:]
        if message.chat.type != "private" and name not in ("id", *COMMANDS_ADMIN):
            return
        if name == "start":
            inc.payload = args[0] if args else ""
            await safe(engine.on_start(inc))
            return
        await safe(engine.on_command(inc, name, args))

    return router


def build_providers(funnel: Funnel) -> Dict[str, Provider]:
    providers: Dict[str, Provider] = {}
    if funnel.payments.yookassa:
        providers["yookassa"] = YooKassaProvider(funnel.payments.yookassa)
    if funnel.payments.crypto:
        providers["crypto"] = CryptoPayProvider(funnel.payments.crypto)
    return providers


async def scheduler(engine: Engine) -> None:
    while True:
        await engine.tick()
        await asyncio.sleep(TICK_SECONDS)


async def publish_commands(bot: Bot, funnel: Funnel) -> None:
    if funnel.bot.language == "ru":
        descriptions = {
            "start": "Начать", "help": "Помощь", "terms": "Условия", "paysupport": "Помощь с оплатой",
            "deleteme": "Удалить мои данные", "stop": "Отключить рекламные сообщения",
            "resume": "Включить рекламные сообщения",
        }
        admin_label = "Админ"
    else:
        descriptions = {
            "start": "Start", "help": "Help", "terms": "Terms", "paysupport": "Payment help",
            "deleteme": "Erase my data", "stop": "Stop promotional messages", "resume": "Resume promotional messages",
        }
        admin_label = "Admin"
    try:
        await bot.set_my_commands([BotCommand(command=c, description=descriptions[c]) for c in COMMANDS_PUBLIC])
        admin = [BotCommand(command=c, description=f"{admin_label}: {c}") for c in COMMANDS_ADMIN]
        for admin_id in funnel.bot.admins:
            public = [BotCommand(command=c, description=descriptions[c]) for c in COMMANDS_PUBLIC]
            await bot.set_my_commands(public + admin, scope=BotCommandScopeChat(chat_id=admin_id))
    except (TelegramAPIError, AiogramError) as exc:
        log.warning("could not publish the command list: %s", exc)


async def run_bot(funnel_path: Path, db_path: Path, token: str, api_base: Optional[str] = None,
                  claim_code: str = "") -> None:
    funnel = load_funnel(funnel_path)
    for warning in funnel.warnings:
        log.warning(warning)
    store = Store(db_path)
    session = AiohttpSession(api=TelegramAPIServer.from_base(api_base)) if api_base else None
    bot = Bot(token, session=session)
    providers = build_providers(funnel)
    engine = Engine(funnel, store, AiogramTransport(bot), providers, funnel_path=str(funnel_path), log=log.info,
                    claim_code=claim_code)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(engine))
    me = await bot.get_me()
    log.info("started as @%s with %d steps and %d products", me.username, len(funnel.steps), len(funnel.products))
    if not engine.all_admins():
        if claim_code:
            log.warning("NO ADMIN YET. Open this link in Telegram to become the administrator: "
                        "https://t.me/%s?start=claim_%s", me.username, claim_code)
        else:
            log.warning("No administrator is set: put your Telegram id into ADMIN_ID in .env (send /id to the bot to see it)")
    else:
        log.info("Send /admin to the bot to open the control panel")
    await publish_commands(bot, funnel)
    engine.resume_broadcasts()
    worker = asyncio.ensure_future(scheduler(engine))
    try:
        await dispatcher.start_polling(
            bot, allowed_updates=["message", "channel_post", "callback_query", "pre_checkout_query", "chat_join_request", "my_chat_member"])
    finally:
        worker.cancel()
        for task in list(engine.tasks):
            task.cancel()
        for provider in providers.values():
            await provider.close()
        await bot.session.close()
        store.close()
