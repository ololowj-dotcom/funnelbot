from __future__ import annotations

from typing import Any, Dict, List

from .access import AccessMixin
from .transport import Blocked, TransportError

CHECKOUT_WINDOW = 3600


class SchedMixin(AccessMixin):
    async def tick(self) -> None:
        jobs = (self.run_waits, self.run_nudges, self.run_polls, self.run_redelivery, self.run_access)
        for job in jobs:
            try:
                await job()
            except Exception as exc:
                self.log(f"scheduler job {job.__name__} failed: {exc!r}")

    async def run_waits(self) -> None:
        now = self.now()
        rows = self.store.many(
            "SELECT id, step FROM users WHERE advance_at IS NOT NULL AND advance_at <= ? AND erased = 0", (now,))
        for row in rows:
            self.store.update_user(row["id"], advance_at=None)
            step = self.funnel.steps.get(row["step"])
            if step is None or not step.next:
                continue
            try:
                await self.enter_step(row["id"], row["id"], step.next)
            except Exception as exc:
                self.log(f"auto-advance of user {row['id']} failed: {exc!r}")

    def nudge_targets(self, step_id: str, nudge_index: int) -> List[str]:
        step = self.funnel.steps[step_id]
        nudge = step.nudges[nudge_index]
        products = [b.pay for row in nudge.buttons for b in row if b.pay]
        return products

    def has_recent_checkout(self, user_id: int, now: int) -> bool:
        row = self.store.one(
            "SELECT id FROM payments WHERE user_id = ? AND status IN ('pending', 'awaiting_proof', 'review') "
            "AND created_at >= ? LIMIT 1", (user_id, now - CHECKOUT_WINDOW))
        return row is not None

    async def run_nudges(self) -> None:
        timed = {sid: min(n.after for n in s.nudges) for sid, s in self.funnel.steps.items() if s.nudges}
        if not timed:
            return
        now = self.now()
        marks = ",".join("?" for _ in timed)
        open_consent = 1 if self.funnel.consent is None else 0
        rows = self.store.many(
            f"SELECT * FROM users WHERE step IN ({marks}) AND stopped = 0 AND blocked = 0 AND erased = 0 "
            "AND (consented_at IS NOT NULL OR ? = 1)", [*timed, open_consent])
        for user in rows:
            if now < user["step_at"] + timed[user["step"]]:
                continue
            try:
                await self.nudge_user(user, now)
            except Exception as exc:
                self.log(f"nudge for user {user['id']} failed: {exc!r}")

    async def nudge_user(self, user: Dict[str, Any], now: int) -> None:
        step = self.funnel.steps[user["step"]]
        sent = set(self.store.nudge_sent(user["id"], step.id))
        due = [i for i, n in enumerate(step.nudges) if user["step_at"] + n.after <= now and i not in sent]
        if not due or self.has_recent_checkout(user["id"], now):
            return
        for i in due:
            self.store.mark_nudge(user["id"], step.id, i, now)
        index = due[-1]
        products = self.nudge_targets(step.id, index)
        if products and self.owned_all(user["id"], products):
            return
        nudge = step.nudges[index]
        await self.send(user["id"], self.fmt(nudge.text, user), self.keyboard(nudge.buttons), nudge.image,
                        user_id=user["id"])

    async def run_polls(self) -> None:
        now = self.now()
        ttl = self.funnel.payments.pending_ttl
        if now - self.last_poll < self.funnel.payments.poll_seconds:
            return
        self.last_poll = now
        self.store.db.execute(
            "UPDATE payments SET status = 'expired' WHERE status = 'pending' AND method IN ('stars', 'telegram', 'test') "
            "AND created_at < ?", (now - ttl,))
        methods = [m for m in ("yookassa", "crypto") if m in self.providers]
        if not methods:
            return
        for payment in self.store.open_payments(methods):
            try:
                state = await self.poll_one(payment)
                if state == "pending" and payment["created_at"] < now - ttl:
                    self.store.update_payment(payment["id"], status="expired")
                    state = "expired"
                if state == "failed":
                    await self.send(payment["user_id"], self.tx("pay_failed"), user_id=payment["user_id"])
                elif state == "expired":
                    await self.send(payment["user_id"], self.tx("pay_expired"), user_id=payment["user_id"])
            except Blocked:
                self.store.update_user(payment["user_id"], blocked=1)
            except TransportError as exc:
                self.log(f"poll of payment {payment['id']} failed: {exc}")

    async def run_redelivery(self) -> None:
        now = self.now()
        for payment in self.store.undelivered():
            if self.retry_at.get(payment["id"], 0) <= now:
                await self.deliver(payment["id"])
