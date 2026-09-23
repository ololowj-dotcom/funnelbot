import asyncio
import base64
from decimal import Decimal

import pytest
from aiohttp import web

from funnelbot.providers import CryptoPayProvider, ProviderError, YooKassaProvider
from funnelbot.schema import Crypto, Receipt, YooKassa


async def serve(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{runner.addresses[0][1]}"


def test_yookassa_create_and_status():
    seen = {}

    async def create(request):
        seen["auth"] = request.headers["Authorization"]
        seen["key"] = request.headers["Idempotence-Key"]
        seen["body"] = await request.json()
        return web.json_response({"id": "pay-1", "status": "pending", "confirmation": {"confirmation_url": "https://pay/1"}})

    async def status(request):
        state = seen.get("state", "pending")
        return web.json_response({"id": request.match_info["id"], "status": state})

    async def scenario():
        app = web.Application()
        app.router.add_post("/v3/payments", create)
        app.router.add_get("/v3/payments/{id}", status)
        app.router.add_get("/v3/payments", lambda r: web.json_response({"items": []}))
        runner, base = await serve(app)
        cfg = YooKassa("shop", "secret", "https://t.me/bot", api_base=base + "/v3",
                       receipt=Receipt(vat_code=1, tax_system_code=2))
        provider = YooKassaProvider(cfg)
        try:
            created = await provider.create(7, Decimal("4900"), "Club", {"email": "a@b.co"})
            assert created.external_id == "pay-1" and created.url == "https://pay/1"
            assert seen["auth"] == "Basic " + base64.b64encode(b"shop:secret").decode()
            body = seen["body"]
            assert body["amount"] == {"value": "4900.00", "currency": "RUB"}
            assert body["metadata"] == {"payment_id": "7"} and body["capture"] is True
            assert body["receipt"]["customer"] == {"email": "a@b.co"}
            assert body["receipt"]["tax_system_code"] == 2
            assert body["receipt"]["items"][0]["vat_code"] == 1
            assert await provider.status("pay-1") == "pending"
            seen["state"] = "succeeded"
            assert await provider.status("pay-1") == "paid"
            seen["state"] = "canceled"
            assert await provider.status("pay-1") == "failed"
            assert "accepted" in await provider.check()
        finally:
            await provider.close()
            await runner.cleanup()

    asyncio.run(scenario())


def test_yookassa_receipt_needs_contact_and_phone_is_digits():
    async def scenario():
        cfg = YooKassa("s", "k", "https://t.me/b", api_base="http://127.0.0.1:1", receipt=Receipt())
        provider = YooKassaProvider(cfg)
        with pytest.raises(ProviderError, match="email or phone"):
            await provider.create(1, Decimal("10"), "X", {})
        await provider.close()

    asyncio.run(scenario())


def test_yookassa_error_is_readable():
    async def refuse(request):
        return web.json_response({"type": "error", "description": "Invalid credentials"}, status=401)

    async def scenario():
        app = web.Application()
        app.router.add_get("/v3/payments", refuse)
        runner, base = await serve(app)
        provider = YooKassaProvider(YooKassa("s", "k", "https://t.me/b", api_base=base + "/v3"))
        try:
            with pytest.raises(ProviderError, match="401.*Invalid credentials"):
                await provider.check()
        finally:
            await provider.close()
            await runner.cleanup()

    asyncio.run(scenario())


def test_provider_network_error():
    async def scenario():
        provider = YooKassaProvider(YooKassa("s", "k", "https://t.me/b", api_base="http://127.0.0.1:1/v3"))
        with pytest.raises(ProviderError, match="network error"):
            await provider.status("x")
        await provider.close()

    asyncio.run(scenario())


def test_crypto_pay_create_and_status():
    seen = {"status": "active"}

    async def create(request):
        seen["token"] = request.headers["Crypto-Pay-API-Token"]
        seen["body"] = await request.json()
        return web.json_response({"ok": True, "result": {"invoice_id": 55, "bot_invoice_url": "https://t.me/CryptoBot?start=IV55"}})

    async def invoices(request):
        seen["ids"] = request.query["invoice_ids"]
        return web.json_response({"ok": True, "result": {"items": [{"invoice_id": 55, "status": seen["status"]}]}})

    async def me(request):
        return web.json_response({"ok": True, "result": {"name": "Shop"}})

    async def bad(request):
        return web.json_response({"ok": False, "error": {"code": 401, "name": "UNAUTHORIZED"}}, status=401)

    async def scenario():
        app = web.Application()
        app.router.add_post("/api/createInvoice", create)
        app.router.add_get("/api/getInvoices", invoices)
        app.router.add_get("/api/getMe", me)
        runner, base = await serve(app)
        provider = CryptoPayProvider(Crypto("tok", "USDT", api_base=base + "/api", expires_in=600))
        try:
            created = await provider.create(9, Decimal("55.50"), "Club", {})
            assert created.external_id == "55" and created.url.startswith("https://t.me/CryptoBot")
            assert seen["token"] == "tok"
            assert seen["body"]["asset"] == "USDT" and seen["body"]["amount"] == "55.5"
            assert seen["body"]["payload"] == "9" and seen["body"]["expires_in"] == 600
            assert await provider.status("55") == "pending"
            seen["status"] = "paid"
            assert await provider.status("55") == "paid"
            seen["status"] = "expired"
            assert await provider.status("55") == "failed"
            assert seen["ids"] == "55"
            assert "Shop" in await provider.check()
        finally:
            await provider.close()
            await runner.cleanup()
        app2 = web.Application()
        app2.router.add_get("/api/getMe", bad)
        runner2, base2 = await serve(app2)
        provider2 = CryptoPayProvider(Crypto("tok", "USDT", api_base=base2 + "/api"))
        try:
            with pytest.raises(ProviderError, match="UNAUTHORIZED"):
                await provider2.check()
        finally:
            await provider2.close()
            await runner2.cleanup()

    asyncio.run(scenario())
