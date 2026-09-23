from __future__ import annotations

from typing import Any, List, Optional, Tuple

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import AiogramError, TelegramAPIError

from .bot import build_providers
from .providers import ProviderError
from .schema import Funnel

Finding = Tuple[str, str, str]
OK, WARN, FAIL = "ok", "warn", "fail"


def channel_chats(funnel: Funnel) -> List[int]:
    seen: List[int] = []
    for product in funnel.products.values():
        for rule in product.access:
            if rule.kind == "channel" and rule.chat is not None and rule.chat not in seen:
                seen.append(rule.chat)
    return seen


async def check_channel(bot: Any, chat: int, me: int) -> List[Finding]:
    subject = f"chat {chat}"
    try:
        info = await bot.get_chat(chat)
    except (TelegramAPIError, AiogramError) as exc:
        return [(FAIL, subject, f"the bot cannot see this chat ({exc}); add the bot to it as an administrator")]
    title = getattr(info, "title", "") or str(chat)
    try:
        member = await bot.get_chat_member(chat, me)
    except (TelegramAPIError, AiogramError) as exc:
        return [(FAIL, subject, f"cannot read the bot's rights in '{title}': {exc}")]
    status = getattr(member, "status", "")
    if status == "creator":
        return [(OK, subject, f"'{title}': the bot is the owner")]
    if status != "administrator":
        return [(FAIL, subject, f"'{title}': the bot is not an administrator; make it one with the rights to invite and ban users")]
    findings: List[Finding] = []
    for right, purpose in (("can_invite_users", "create join-request links"), ("can_restrict_members", "remove members when access ends")):
        if not getattr(member, right, False):
            findings.append((FAIL, subject, f"'{title}': the bot lacks the right to {purpose} ({right})"))
    return findings or [(OK, subject, f"'{title}': the bot is an administrator with the needed rights")]


async def diagnose(funnel: Funnel, token: str, api_base: Optional[str] = None) -> List[Finding]:
    findings: List[Finding] = []
    if not token:
        return [(FAIL, "token", "BOT_TOKEN is empty: put the token from @BotFather into the .env file")]
    session = AiohttpSession(api=TelegramAPIServer.from_base(api_base)) if api_base else None
    bot = Bot(token, session=session)
    providers = build_providers(funnel)
    try:
        try:
            me = await bot.get_me()
        except (TelegramAPIError, AiogramError) as exc:
            return [(FAIL, "token", f"Telegram refused the token: {exc}")]
        findings.append((OK, "token", f"the bot is @{me.username}"))
        for chat in channel_chats(funnel):
            findings += await check_channel(bot, chat, me.id)
        manager = funnel.bot.manager_chat
        if manager is not None:
            try:
                await bot.get_chat(manager)
                findings.append((OK, "manager_chat", "reachable"))
            except (TelegramAPIError, AiogramError) as exc:
                findings.append((FAIL, "manager_chat", f"the bot cannot write there ({exc}); add it to the chat and press /start there"))
        else:
            findings.append((WARN, "manager_chat", "not set: manager buttons, manual payments and order cards are unavailable"))
        if not funnel.bot.admins:
            findings.append((WARN, "admins", "empty: nobody can use /stats, /broadcast, /refund (send /id to the bot to learn your id)"))
        tg = funnel.payments.telegram
        if tg and ":TEST:" in tg.provider_token:
            findings.append((WARN, "payments.telegram", "the provider token is a TEST token: real cards will not be charged"))
        if not funnel.payments.stars:
            findings.append((WARN, "payments.stars", "Stars are off: Telegram's rules require Stars for digital goods and services"))
        for name, provider in providers.items():
            try:
                findings.append((OK, f"payments.{name}", await provider.check()))
            except ProviderError as exc:
                findings.append((FAIL, f"payments.{name}", str(exc)))
        for warning in funnel.warnings:
            findings.append((WARN, "funnel", warning))
    finally:
        for provider in providers.values():
            await provider.close()
        await bot.session.close()
    return findings


async def bot_username(token: str, api_base: Optional[str] = None) -> str:
    session = AiohttpSession(api=TelegramAPIServer.from_base(api_base)) if api_base else None
    bot = Bot(token, session=session)
    try:
        me = await bot.get_me()
        return me.username or ""
    except (TelegramAPIError, AiogramError, OSError) as exc:
        raise ValueError(str(exc)) from exc
    finally:
        await bot.session.close()
