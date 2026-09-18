from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = 1

SCHEMA = r'''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS servers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  provider TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT 'VPS',
  amount_minor INTEGER NOT NULL CHECK(amount_minor >= 0),
  currency TEXT NOT NULL DEFAULT 'RUB',
  cycle TEXT NOT NULL DEFAULT 'monthly',
  cycle_days INTEGER,
  next_due TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_servers_due ON servers(active, next_due);
CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
  amount_minor INTEGER NOT NULL,
  currency TEXT NOT NULL,
  due_date TEXT NOT NULL,
  paid_at TEXT NOT NULL,
  next_due TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_payments_paid ON payments(paid_at);
CREATE TABLE IF NOT EXISTS notification_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
  due_date TEXT NOT NULL,
  kind TEXT NOT NULL,
  sent_at TEXT NOT NULL,
  UNIQUE(server_id, due_date, kind)
);
CREATE TABLE IF NOT EXISTS snoozes (
  server_id INTEGER PRIMARY KEY REFERENCES servers(id) ON DELETE CASCADE,
  until_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_events (
  event_key TEXT PRIMARY KEY,
  created_at TEXT NOT NULL
);
'''


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=30000")
            yield c
            c.commit()
        finally:
            c.close()

    def migrate(self) -> None:
        with self.conn() as c:
            c.executescript(SCHEMA)
            c.execute("INSERT INTO meta(key,value) VALUES('schema_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(SCHEMA_VERSION),))

    def integrity(self) -> dict:
        with self.conn() as c:
            integrity = c.execute("PRAGMA integrity_check").fetchone()[0]
            version = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        return {"integrity": integrity, "schema_version": int(version), "size": self.path.stat().st_size if self.path.exists() else 0}

    def backup_to(self, out: Path) -> Path:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(self.path)
        dst = sqlite3.connect(out)
        try:
            src.backup(dst)
            check = dst.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise RuntimeError(f"backup integrity_check: {check}")
        finally:
            dst.close(); src.close()
        return out

    @staticmethod
    def _row(row):
        return dict(row) if row else None

    def add_server(self, *, name: str, provider: str, amount_minor: int, currency: str, next_due: str, cycle: str, cycle_days: int | None = None, notes: str = "") -> int:
        ts = now_iso()
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO servers(name,provider,amount_minor,currency,next_due,cycle,cycle_days,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (name.strip(), provider.strip(), amount_minor, currency.upper(), next_due, cycle, cycle_days, notes.strip(), ts, ts),
            )
            return int(cur.lastrowid)

    def list_servers(self, active_only: bool = True) -> list[dict]:
        q = "SELECT * FROM servers" + (" WHERE active=1" if active_only else "") + " ORDER BY date(next_due), lower(name)"
        with self.conn() as c:
            return [dict(r) for r in c.execute(q).fetchall()]

    def get_server(self, server_id: int) -> dict | None:
        with self.conn() as c:
            return self._row(c.execute("SELECT * FROM servers WHERE id=?", (server_id,)).fetchone())

    def update_due(self, server_id: int, next_due: str) -> None:
        with self.conn() as c:
            c.execute("UPDATE servers SET next_due=?, updated_at=? WHERE id=?", (next_due, now_iso(), server_id))

    def set_active(self, server_id: int, active: bool) -> None:
        with self.conn() as c:
            c.execute("UPDATE servers SET active=?, updated_at=? WHERE id=?", (1 if active else 0, now_iso(), server_id))

    def delete_server(self, server_id: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM servers WHERE id=?", (server_id,))

    def add_payment(self, server_id: int, amount_minor: int, currency: str, due_date: str, next_due: str, note: str = "") -> int:
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO payments(server_id,amount_minor,currency,due_date,paid_at,next_due,note) VALUES(?,?,?,?,?,?,?)",
                (server_id, amount_minor, currency, due_date, now_iso(), next_due, note),
            )
            c.execute("UPDATE servers SET next_due=?,updated_at=? WHERE id=?", (next_due, now_iso(), server_id))
            c.execute("DELETE FROM snoozes WHERE server_id=?", (server_id,))
            return int(cur.lastrowid)

    def recent_payments(self, limit: int = 30) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT p.*, s.name, s.provider FROM payments p JOIN servers s ON s.id=p.server_id ORDER BY datetime(p.paid_at) DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def payments_between(self, start_iso: str, end_iso: str) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT p.*, s.name,s.provider FROM payments p JOIN servers s ON s.id=p.server_id WHERE datetime(p.paid_at)>=datetime(?) AND datetime(p.paid_at)<datetime(?) ORDER BY datetime(p.paid_at)",
                (start_iso, end_iso),
            ).fetchall()
            return [dict(r) for r in rows]

    def due_between(self, start_date: str, end_date: str) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("SELECT * FROM servers WHERE active=1 AND date(next_due)>=date(?) AND date(next_due)<=date(?) ORDER BY date(next_due)", (start_date, end_date)).fetchall()
            return [dict(r) for r in rows]

    def overdue(self, today: str) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM servers WHERE active=1 AND date(next_due)<date(?) ORDER BY date(next_due)", (today,)).fetchall()]

    def notification_sent(self, server_id: int, due_date: str, kind: str) -> bool:
        with self.conn() as c:
            return c.execute("SELECT 1 FROM notification_log WHERE server_id=? AND due_date=? AND kind=?", (server_id, due_date, kind)).fetchone() is not None

    def mark_notification(self, server_id: int, due_date: str, kind: str) -> None:
        with self.conn() as c:
            c.execute("INSERT OR IGNORE INTO notification_log(server_id,due_date,kind,sent_at) VALUES(?,?,?,?)", (server_id, due_date, kind, now_iso()))

    def snooze_until(self, server_id: int, until_at: str) -> None:
        with self.conn() as c:
            c.execute("INSERT INTO snoozes(server_id,until_at) VALUES(?,?) ON CONFLICT(server_id) DO UPDATE SET until_at=excluded.until_at", (server_id, until_at))

    def is_snoozed(self, server_id: int, now_value: str) -> bool:
        with self.conn() as c:
            row = c.execute("SELECT until_at FROM snoozes WHERE server_id=?", (server_id,)).fetchone()
        return bool(row and row[0] > now_value)


    def due_snoozes(self, now_value: str) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT s.*, z.until_at FROM snoozes z JOIN servers s ON s.id=z.server_id WHERE s.active=1 AND z.until_at<=? ORDER BY z.until_at",
                (now_value,),
            ).fetchall()
            return [dict(r) for r in rows]

    def clear_snooze(self, server_id: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM snoozes WHERE server_id=?", (server_id,))

    def event_exists(self, key: str) -> bool:
        with self.conn() as c:
            return c.execute("SELECT 1 FROM app_events WHERE event_key=?", (key,)).fetchone() is not None

    def mark_event(self, key: str) -> None:
        with self.conn() as c:
            c.execute("INSERT OR IGNORE INTO app_events(event_key,created_at) VALUES(?,?)", (key, now_iso()))
