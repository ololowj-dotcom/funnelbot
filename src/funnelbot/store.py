from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL DEFAULT '',
    first_name TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    step TEXT NOT NULL DEFAULT '',
    step_at INTEGER NOT NULL DEFAULT 0,
    advance_at INTEGER,
    history TEXT NOT NULL DEFAULT '[]',
    answers TEXT NOT NULL DEFAULT '{}',
    consented_at INTEGER,
    stopped INTEGER NOT NULL DEFAULT 0,
    blocked INTEGER NOT NULL DEFAULT 0,
    erased INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    last_seen INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    product_id TEXT NOT NULL,
    method TEXT NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    external_id TEXT,
    charge_id TEXT,
    url TEXT,
    origin_step TEXT,
    created_at INTEGER NOT NULL,
    paid_at INTEGER,
    delivered INTEGER NOT NULL DEFAULT 0,
    meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS payments_user ON payments(user_id);
CREATE INDEX IF NOT EXISTS payments_status ON payments(status);
CREATE UNIQUE INDEX IF NOT EXISTS payments_external ON payments(method, external_id) WHERE external_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    product_id TEXT NOT NULL,
    payment_id INTEGER,
    chat INTEGER NOT NULL,
    expires_at INTEGER,
    joined INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    reminded TEXT NOT NULL DEFAULT '[]',
    remove_attempts INTEGER NOT NULL DEFAULT 0,
    next_try INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    ended_at INTEGER
);
CREATE INDEX IF NOT EXISTS grants_user ON grants(user_id);
CREATE INDEX IF NOT EXISTS grants_status ON grants(status);
CREATE TABLE IF NOT EXISTS nudges_sent (
    user_id INTEGER NOT NULL,
    step_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    sent_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, step_id, idx)
);
CREATE TABLE IF NOT EXISTS kv (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS broadcasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    segment TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    total INTEGER NOT NULL DEFAULT 0,
    sent INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    cursor INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
"""

JSON_COLUMNS = {"history", "answers", "reminded", "meta"}
USER_COLUMNS = {
    "username", "first_name", "source", "step", "step_at", "advance_at", "history", "answers",
    "consented_at", "stopped", "blocked", "erased", "last_seen",
}
PAYMENT_COLUMNS = {
    "status", "external_id", "charge_id", "url", "paid_at", "delivered", "meta", "origin_step",
}
GRANT_COLUMNS = {"expires_at", "joined", "status", "reminded", "remove_attempts", "ended_at", "next_try"}
BROADCAST_COLUMNS = {"status", "total", "sent", "failed", "cursor"}
OPEN_PAYMENT = ("pending", "awaiting_proof", "review")


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    data = dict(row)
    for key in JSON_COLUMNS:
        if key in data and isinstance(data[key], str):
            data[key] = json.loads(data[key])
    return data


def encode(values: Dict[str, Any]) -> Dict[str, Any]:
    return {k: json.dumps(v, ensure_ascii=False) if k in JSON_COLUMNS else v for k, v in values.items()}


class Store:
    def __init__(self, path: Union[str, Path]):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def one(self, sql: str, args: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
        return row_to_dict(self.db.execute(sql, args).fetchone())

    def many(self, sql: str, args: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        return [row_to_dict(r) for r in self.db.execute(sql, args).fetchall()]

    def scalar(self, sql: str, args: Sequence[Any] = ()) -> Any:
        row = self.db.execute(sql, args).fetchone()
        return row[0] if row else None

    def update(self, table: str, allowed: Iterable[str], row_id: int, values: Dict[str, Any]) -> int:
        values = encode(values)
        bad = set(values) - set(allowed)
        if bad:
            raise KeyError(f"cannot update {table} columns: {sorted(bad)}")
        if not values:
            return 0
        sets = ", ".join(f"{k} = ?" for k in values)
        cur = self.db.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*values.values(), row_id])
        return cur.rowcount

    def user(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self.one("SELECT * FROM users WHERE id = ?", (user_id,))

    def upsert_user(self, user_id: int, username: str, first_name: str, now: int) -> Dict[str, Any]:
        existing = self.user(user_id)
        if existing is None:
            self.db.execute(
                "INSERT INTO users (id, username, first_name, created_at, last_seen) VALUES (?, ?, ?, ?, ?)",
                (user_id, username or "", first_name or "", now, now),
            )
        elif not existing["erased"]:
            self.db.execute(
                "UPDATE users SET username = ?, first_name = COALESCE(NULLIF(?, ''), first_name), last_seen = ? WHERE id = ?",
                (username or "", first_name or "", now, user_id),
            )
        else:
            self.db.execute(
                "UPDATE users SET username = ?, first_name = ?, last_seen = ?, erased = 0, blocked = 0 WHERE id = ?",
                (username or "", first_name or "", now, user_id),
            )
        return self.user(user_id)

    def update_user(self, user_id: int, **values: Any) -> None:
        values = encode(values)
        bad = set(values) - USER_COLUMNS
        if bad:
            raise KeyError(f"cannot update users columns: {sorted(bad)}")
        if not values:
            return
        sets = ", ".join(f"{k} = ?" for k in values)
        self.db.execute(f"UPDATE users SET {sets} WHERE id = ?", [*values.values(), user_id])

    def set_answer(self, user_id: int, key: str, value: str) -> None:
        user = self.user(user_id)
        answers = dict(user["answers"]) if user else {}
        answers[key] = value
        self.update_user(user_id, answers=answers)

    def erase_user(self, user_id: int) -> None:
        self.db.execute(
            "UPDATE users SET username = '', first_name = '', answers = '{}', history = '[]', step = '', "
            "advance_at = NULL, consented_at = NULL, erased = 1 WHERE id = ?",
            (user_id,),
        )
        self.db.execute("DELETE FROM nudges_sent WHERE user_id = ?", (user_id,))

    def add_payment(self, user_id: int, product_id: str, method: str, amount: str, currency: str,
                    status: str, now: int, origin_step: Optional[str] = None,
                    meta: Optional[Dict[str, Any]] = None, external_id: Optional[str] = None) -> int:
        cur = self.db.execute(
            "INSERT INTO payments (user_id, product_id, method, amount, currency, status, origin_step, created_at, meta, external_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, product_id, method, amount, currency, status, origin_step, now,
             json.dumps(meta or {}, ensure_ascii=False), external_id),
        )
        return int(cur.lastrowid)

    def payment(self, payment_id: int) -> Optional[Dict[str, Any]]:
        return self.one("SELECT * FROM payments WHERE id = ?", (payment_id,))

    def payment_by_external(self, method: str, external_id: str) -> Optional[Dict[str, Any]]:
        return self.one("SELECT * FROM payments WHERE method = ? AND external_id = ?", (method, external_id))

    def payment_by_charge(self, charge_id: str) -> Optional[Dict[str, Any]]:
        return self.one("SELECT * FROM payments WHERE charge_id = ?", (charge_id,))

    def update_payment(self, payment_id: int, **values: Any) -> None:
        self.update("payments", PAYMENT_COLUMNS, payment_id, values)

    def claim_payment(self, payment_id: int, paid_at: int, charge_id: Optional[str]) -> bool:
        cur = self.db.execute(
            "UPDATE payments SET status = 'paid', paid_at = ?, charge_id = COALESCE(?, charge_id) "
            "WHERE id = ? AND status IN ('pending', 'awaiting_proof', 'review', 'expired', 'failed')",
            (paid_at, charge_id, payment_id),
        )
        return cur.rowcount == 1

    def open_payments(self, methods: Sequence[str]) -> List[Dict[str, Any]]:
        marks = ",".join("?" for _ in methods)
        return self.many(f"SELECT * FROM payments WHERE status = 'pending' AND method IN ({marks}) ORDER BY id", list(methods))

    def undelivered(self) -> List[Dict[str, Any]]:
        return self.many("SELECT * FROM payments WHERE status = 'paid' AND delivered = 0 ORDER BY id")

    def user_payments(self, user_id: int) -> List[Dict[str, Any]]:
        return self.many("SELECT * FROM payments WHERE user_id = ? ORDER BY id", (user_id,))

    def owned_products(self, user_id: int) -> List[str]:
        rows = self.many("SELECT DISTINCT product_id FROM payments WHERE user_id = ? AND status = 'paid'", (user_id,))
        return [r["product_id"] for r in rows]

    def latest_open_payment(self, user_id: int, statuses: Sequence[str]) -> Optional[Dict[str, Any]]:
        marks = ",".join("?" for _ in statuses)
        return self.one(
            f"SELECT * FROM payments WHERE user_id = ? AND status IN ({marks}) ORDER BY id DESC LIMIT 1",
            [user_id, *statuses],
        )

    def add_grant(self, user_id: int, product_id: str, payment_id: Optional[int], chat: int,
                  expires_at: Optional[int], now: int) -> int:
        cur = self.db.execute(
            "INSERT INTO grants (user_id, product_id, payment_id, chat, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, product_id, payment_id, chat, expires_at, now),
        )
        return int(cur.lastrowid)

    def grant(self, grant_id: int) -> Optional[Dict[str, Any]]:
        return self.one("SELECT * FROM grants WHERE id = ?", (grant_id,))

    def update_grant(self, grant_id: int, **values: Any) -> None:
        self.update("grants", GRANT_COLUMNS, grant_id, values)

    def live_grant(self, user_id: int, chat: int) -> Optional[Dict[str, Any]]:
        return self.one(
            "SELECT * FROM grants WHERE user_id = ? AND chat = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
            (user_id, chat),
        )

    def live_grant_for_product(self, user_id: int, product_id: str, chat: int) -> Optional[Dict[str, Any]]:
        return self.one(
            "SELECT * FROM grants WHERE user_id = ? AND product_id = ? AND chat = ? AND status = 'active' "
            "ORDER BY id DESC LIMIT 1",
            (user_id, product_id, chat),
        )

    def user_grants(self, user_id: int, only_active: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM grants WHERE user_id = ?"
        if only_active:
            sql += " AND status = 'active'"
        return self.many(sql + " ORDER BY id", (user_id,))

    def active_grants(self) -> List[Dict[str, Any]]:
        return self.many("SELECT * FROM grants WHERE status = 'active' ORDER BY id")

    def nudge_sent(self, user_id: int, step_id: str) -> List[int]:
        rows = self.many("SELECT idx FROM nudges_sent WHERE user_id = ? AND step_id = ?", (user_id, step_id))
        return [r["idx"] for r in rows]

    def mark_nudge(self, user_id: int, step_id: str, idx: int, now: int) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO nudges_sent (user_id, step_id, idx, sent_at) VALUES (?, ?, ?, ?)",
            (user_id, step_id, idx, now),
        )

    def clear_nudges(self, user_id: int) -> None:
        self.db.execute("DELETE FROM nudges_sent WHERE user_id = ?", (user_id,))

    def kv_get(self, key: str) -> Optional[str]:
        row = self.db.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
        return row[0] if row else None

    def kv_set(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)", (key, value))

    def kv_delete(self, key: str) -> None:
        self.db.execute("DELETE FROM kv WHERE k = ?", (key,))

    def add_broadcast(self, admin_id: int, chat_id: int, message_id: int, segment: str, total: int, now: int) -> int:
        cur = self.db.execute(
            "INSERT INTO broadcasts (admin_id, chat_id, message_id, segment, total, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (admin_id, chat_id, message_id, segment, total, now),
        )
        return int(cur.lastrowid)

    def broadcast(self, broadcast_id: int) -> Optional[Dict[str, Any]]:
        return self.one("SELECT * FROM broadcasts WHERE id = ?", (broadcast_id,))

    def update_broadcast(self, broadcast_id: int, **values: Any) -> None:
        self.update("broadcasts", BROADCAST_COLUMNS, broadcast_id, values)

    def running_broadcasts(self) -> List[Dict[str, Any]]:
        return self.many("SELECT * FROM broadcasts WHERE status = 'running' ORDER BY id")

    def audience(self, segment: str, now: int, admin_id: Optional[int] = None) -> List[int]:
        base = "SELECT id FROM users WHERE erased = 0 AND blocked = 0 AND stopped = 0"
        if segment == "test":
            return [admin_id] if admin_id is not None else []
        if segment == "all":
            sql, args = base, []
        elif segment == "paid":
            sql, args = base + " AND id IN (SELECT user_id FROM payments WHERE status = 'paid')", []
        elif segment == "unpaid":
            sql, args = base + " AND id NOT IN (SELECT user_id FROM payments WHERE status = 'paid')", []
        elif segment == "active":
            sql, args = base + " AND id IN (SELECT user_id FROM grants WHERE status = 'active')", []
        elif segment == "expired":
            sql = (base + " AND id IN (SELECT user_id FROM grants WHERE status = 'ended')"
                   " AND id NOT IN (SELECT user_id FROM grants WHERE status = 'active')")
            args = []
        elif segment.startswith("step:"):
            sql, args = base + " AND step = ?", [segment[5:]]
        elif segment.startswith("source:"):
            sql, args = base + " AND source = ?", [segment[7:]]
        else:
            raise ValueError(f"unknown segment '{segment}'")
        return [r["id"] for r in self.many(sql + " ORDER BY id", args)]

    def stats(self, now: int) -> Dict[str, Any]:
        day = now - 86400
        week = now - 7 * 86400
        revenue: Dict[str, Dict[str, str]] = {}
        for row in self.many(
            "SELECT method, currency, amount, paid_at FROM payments WHERE status = 'paid' AND method NOT IN ('grant', 'test')"
        ):
            bucket = revenue.setdefault(row["currency"], {"total": 0, "day": 0, "week": 0})
            value = float(row["amount"])
            bucket["total"] += value
            if row["paid_at"] and row["paid_at"] >= day:
                bucket["day"] += value
            if row["paid_at"] and row["paid_at"] >= week:
                bucket["week"] += value
        return {
            "users": self.scalar("SELECT COUNT(*) FROM users WHERE erased = 0"),
            "new_day": self.scalar("SELECT COUNT(*) FROM users WHERE created_at >= ? AND erased = 0", (day,)),
            "new_week": self.scalar("SELECT COUNT(*) FROM users WHERE created_at >= ? AND erased = 0", (week,)),
            "blocked": self.scalar("SELECT COUNT(*) FROM users WHERE blocked = 1 AND erased = 0"),
            "buyers": self.scalar("SELECT COUNT(DISTINCT user_id) FROM payments WHERE status = 'paid' AND method NOT IN ('grant', 'test')"),
            "payments": self.scalar("SELECT COUNT(*) FROM payments WHERE status = 'paid' AND method NOT IN ('grant', 'test')"),
            "refunded": self.scalar("SELECT COUNT(*) FROM payments WHERE status = 'refunded'"),
            "pending": self.scalar("SELECT COUNT(*) FROM payments WHERE status IN ('pending', 'awaiting_proof', 'review')"),
            "active_access": self.scalar("SELECT COUNT(*) FROM grants WHERE status = 'active'"),
            "revenue": revenue,
            "by_step": {r["step"]: r["n"] for r in self.many(
                "SELECT step, COUNT(*) AS n FROM users WHERE erased = 0 AND step != '' GROUP BY step ORDER BY n DESC")},
            "by_source": {r["source"]: r["n"] for r in self.many(
                "SELECT source, COUNT(*) AS n FROM users WHERE erased = 0 AND source != '' GROUP BY source ORDER BY n DESC")},
        }

    def leads(self) -> List[Dict[str, Any]]:
        return self.many("SELECT * FROM users WHERE erased = 0 ORDER BY created_at")
