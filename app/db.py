from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .default_emojis import DEFAULT_CUSTOM_EMOJIS

SCHEMA_VERSION = 10

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
  ip TEXT NOT NULL DEFAULT '',
  country TEXT NOT NULL DEFAULT '',
  purpose TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '',
  deleted_at TEXT,
  archived_at TEXT,
  monitor_enabled INTEGER NOT NULL DEFAULT 0,
  billing_mode TEXT NOT NULL DEFAULT 'scheduled',
  balance_minor INTEGER NOT NULL DEFAULT 0,
  balance_alert_days INTEGER NOT NULL DEFAULT 3,
  balance_updated_at TEXT,
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
CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS emoji_settings (
  slot TEXT PRIMARY KEY,
  custom_emoji_id TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS monitor_state (
  server_id INTEGER PRIMARY KEY REFERENCES servers(id) ON DELETE CASCADE,
  is_down INTEGER NOT NULL DEFAULT 0,
  fail_count INTEGER NOT NULL DEFAULT 0,
  success_count INTEGER NOT NULL DEFAULT 0,
  last_check TEXT,
  last_change TEXT
);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_key TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  server_id INTEGER REFERENCES servers(id) ON DELETE CASCADE,
  due_date TEXT,
  text TEXT NOT NULL,
  created_at TEXT NOT NULL,
  sent_at TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT NOT NULL DEFAULT '',
  next_attempt_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox(sent_at, next_attempt_at, id);
CREATE TABLE IF NOT EXISTS runtime_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS currency_settings (
  code TEXT PRIMARY KEY,
  active INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 100,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_settings (
  provider TEXT PRIMARY KEY COLLATE NOCASE,
  cabinet_url TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);
'''

DEFAULT_SETTINGS = {
    "reminder_days": "7,3,1,0",
    "overdue_daily": "1",
    "monthly_report_enabled": "1",
    "report_day": "1",
    "report_hour": "10",
    "report_minute": "0",
    "billing_cycles": "weekly,monthly,quarterly,yearly",
    "monitoring_enabled": "0",
    "monitor_interval": "180",
    "monitor_failures": "3",
    "monitor_recovery": "2",
    "monitor_timeout": "3",
    "monitor_method": "auto",
    "monitor_tcp_port": "22",
    "payment_reminder_time": "10:00",
    "auto_update_enabled": "0",
    "auto_update_manifest_url": "",
    "update_check_enabled": "1",
    "update_last_check_day": "",
    "update_last_offered": "",
    "update_remind_after": "",
    "update_ignored_version": "",
    "update_result_notified": "",
    "backup_keep_days": "30",
    "backup_keep_count": "30",
}


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
            # Forward-only, additive migrations for databases created by v2.0/v2.1.
            existing = {str(r[1]) for r in c.execute("PRAGMA table_info(servers)").fetchall()}
            additions = {
                "ip": "TEXT NOT NULL DEFAULT ''",
                "country": "TEXT NOT NULL DEFAULT ''",
                "purpose": "TEXT NOT NULL DEFAULT ''",
                "tags": "TEXT NOT NULL DEFAULT ''",
                "deleted_at": "TEXT",
                "archived_at": "TEXT",
                "monitor_enabled": "INTEGER NOT NULL DEFAULT 0",
                "billing_mode": "TEXT NOT NULL DEFAULT 'scheduled'",
                "balance_minor": "INTEGER NOT NULL DEFAULT 0",
                "balance_alert_days": "INTEGER NOT NULL DEFAULT 3",
                "balance_updated_at": "TEXT",
            }
            for column, ddl in additions.items():
                if column not in existing:
                    c.execute(f"ALTER TABLE servers ADD COLUMN {column} {ddl}")
            c.execute("CREATE INDEX IF NOT EXISTS idx_servers_deleted ON servers(deleted_at)")
            ts = now_iso()
            for key, value in DEFAULT_SETTINGS.items():
                c.execute(
                    "INSERT OR IGNORE INTO app_settings(key,value,updated_at) VALUES(?,?,?)",
                    (key, value, ts),
                )
            for code, order in (("RUB", 10), ("EUR", 20), ("USD", 30)):
                c.execute(
                    "INSERT OR IGNORE INTO currency_settings(code,active,sort_order,created_at,updated_at) VALUES(?,1,?,?,?)",
                    (code, order, ts, ts),
                )
            c.execute(
                "INSERT INTO meta(key,value) VALUES('schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    def integrity(self) -> dict:
        with self.conn() as c:
            integrity = c.execute("PRAGMA integrity_check").fetchone()[0]
            version = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        return {
            "integrity": integrity,
            "schema_version": int(version),
            "size": self.path.stat().st_size if self.path.exists() else 0,
        }

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
            dst.close()
            src.close()
        return out

    @staticmethod
    def _row(row):
        return dict(row) if row else None

    def add_server(self, *, name: str, provider: str, amount_minor: int, currency: str, next_due: str, cycle: str, cycle_days: int | None = None, notes: str = "", billing_mode: str = "scheduled", balance_minor: int = 0, balance_alert_days: int = 3) -> int:
        currency = currency.upper().strip()
        if not self.currency_exists(currency):
            raise ValueError("Неизвестная валюта")
        ts = now_iso()
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO servers(name,provider,amount_minor,currency,next_due,cycle,cycle_days,notes,billing_mode,balance_minor,balance_alert_days,balance_updated_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (name.strip(), provider.strip(), amount_minor, currency, next_due, cycle, cycle_days, notes.strip(), billing_mode, int(balance_minor), int(balance_alert_days), ts if billing_mode == "balance" else None, ts, ts),
            )
            return int(cur.lastrowid)


    def demo_server_ids(self) -> list[int]:
        with self.conn() as c:
            row = c.execute("SELECT value FROM meta WHERE key='demo_server_ids'").fetchone()
        if not row or not str(row[0]).strip():
            return []
        ids: list[int] = []
        for raw in str(row[0]).split(','):
            try:
                ids.append(int(raw.strip()))
            except ValueError:
                pass
        if not ids:
            return []
        with self.conn() as c:
            existing = {int(r[0]) for r in c.execute(
                f"SELECT id FROM servers WHERE id IN ({','.join('?' for _ in ids)})", ids
            ).fetchall()}
        return [sid for sid in ids if sid in existing]

    def demo_server_count(self) -> int:
        return len(self.demo_server_ids())

    def add_demo_servers(self, base_date: date | None = None) -> int:
        """Create an idempotent demo set with dates relative to base_date."""
        if self.demo_server_ids():
            return 0
        base_date = base_date or date.today()
        demo = [
            ("demo-web-hel1", "DemoCloud", 19900, "RUB", -5, "monthly", "192.0.2.10", "Финляндия", "demo,web", "Демо: просроченный платёж"),
            ("demo-api-fra1", "DemoCloud", 499, "USD", 0, "monthly", "192.0.2.20", "Германия", "demo,prod", "Демо: оплата сегодня"),
            ("demo-vpn-ams1", "DemoVPS", 699, "EUR", 1, "monthly", "192.0.2.30", "Нидерланды", "demo,vpn", "Демо: оплата завтра"),
            ("demo-db-par1", "DemoVPS", 29900, "RUB", 3, "quarterly", "198.51.100.10", "Франция", "demo,storage", "Демо: ближайшая оплата через 3 дня"),
            ("demo-backup-nyc1", "DemoHost", 899, "USD", 7, "yearly", "198.51.100.20", "США", "demo,backup", "Демо: оплата через неделю"),
            ("demo-monitor-lon1", "DemoHost", 1299, "EUR", 30, "monthly", "203.0.113.10", "Великобритания", "demo,other", "Демо: более поздняя оплата"),
        ]
        ids: list[int] = []
        for name, provider, amount, currency, offset, cycle, ip, country, tags, notes in demo:
            sid = self.add_server(
                name=name, provider=provider, amount_minor=amount, currency=currency,
                next_due=(base_date + timedelta(days=offset)).isoformat(),
                cycle=cycle, notes=notes,
            )
            self.update_server_field(sid, "ip", ip)
            self.update_server_field(sid, "country", country)
            self.update_server_field(sid, "tags", tags)
            ids.append(sid)
        for provider in ("DemoCloud", "DemoVPS", "DemoHost"):
            self.set_provider_url(provider, "https://example.com/")
        with self.conn() as c:
            c.execute(
                "INSERT INTO meta(key,value) VALUES('demo_server_ids',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (','.join(str(x) for x in ids),),
            )
        return len(ids)

    def delete_demo_servers(self) -> int:
        ids = self.demo_server_ids()
        if not ids:
            with self.conn() as c:
                c.execute("DELETE FROM meta WHERE key='demo_server_ids'")
            return 0
        with self.conn() as c:
            q = ','.join('?' for _ in ids)
            count = int(c.execute(f"SELECT COUNT(*) FROM servers WHERE id IN ({q})", ids).fetchone()[0])
            c.execute(f"DELETE FROM servers WHERE id IN ({q})", ids)
            c.execute("DELETE FROM meta WHERE key='demo_server_ids'")
            for provider in ("DemoCloud", "DemoVPS", "DemoHost"):
                used = c.execute(
                    "SELECT 1 FROM servers WHERE lower(trim(provider))=lower(trim(?)) LIMIT 1",
                    (provider,),
                ).fetchone()
                if not used:
                    c.execute("DELETE FROM provider_settings WHERE lower(trim(provider))=lower(trim(?))", (provider,))
        return count

    def list_servers(self, active_only: bool = True) -> list[dict]:
        q = "SELECT * FROM servers" + (" WHERE active=1 AND deleted_at IS NULL AND archived_at IS NULL" if active_only else "") + " ORDER BY date(next_due), lower(name)"
        with self.conn() as c:
            return [dict(r) for r in c.execute(q).fetchall()]

    def list_providers(self) -> list[str]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT provider, COUNT(*) AS n FROM servers WHERE active=1 AND deleted_at IS NULL AND archived_at IS NULL AND trim(provider)<>'' GROUP BY provider ORDER BY n DESC, lower(provider)"
            ).fetchall()
        return [str(r["provider"]) for r in rows]

    def list_currencies(self, active_only: bool = False) -> list[dict]:
        q = "SELECT code,active,sort_order FROM currency_settings"
        if active_only:
            q += " WHERE active=1"
        q += " ORDER BY sort_order, code"
        with self.conn() as c:
            return [dict(r) for r in c.execute(q).fetchall()]

    def active_currency_codes(self) -> tuple[str, ...]:
        rows = self.list_currencies(active_only=True)
        return tuple(str(r["code"]) for r in rows)

    def currency_exists(self, code: str) -> bool:
        with self.conn() as c:
            return c.execute("SELECT 1 FROM currency_settings WHERE code=?", (code.upper().strip(),)).fetchone() is not None

    def add_currency(self, code: str) -> None:
        code = code.upper().strip()
        if not code or len(code) > 8 or not code.replace("_", "").isalnum():
            raise ValueError("Код валюты: 2–8 букв/цифр, например GBP или USDT")
        with self.conn() as c:
            row = c.execute("SELECT COALESCE(MAX(sort_order),0)+10 FROM currency_settings").fetchone()
            order = int(row[0] or 10)
            ts = now_iso()
            c.execute(
                "INSERT INTO currency_settings(code,active,sort_order,created_at,updated_at) VALUES(?,1,?,?,?) "
                "ON CONFLICT(code) DO UPDATE SET active=1, updated_at=excluded.updated_at",
                (code, order, ts, ts),
            )

    def toggle_currency(self, code: str) -> bool:
        code = code.upper().strip()
        with self.conn() as c:
            row = c.execute("SELECT active FROM currency_settings WHERE code=?", (code,)).fetchone()
            if not row:
                raise ValueError("Валюта не найдена")
            current = bool(row[0])
            if current:
                count = int(c.execute("SELECT COUNT(*) FROM currency_settings WHERE active=1").fetchone()[0])
                if count <= 1:
                    raise ValueError("Должна остаться хотя бы одна активная валюта")
            c.execute("UPDATE currency_settings SET active=?, updated_at=? WHERE code=?", (0 if current else 1, now_iso(), code))
            return not current

    def reset_currencies(self) -> None:
        ts = now_iso()
        with self.conn() as c:
            c.execute("UPDATE currency_settings SET active=0, updated_at=?", (ts,))
            for code, order in (("RUB", 10), ("EUR", 20), ("USD", 30)):
                c.execute(
                    "INSERT INTO currency_settings(code,active,sort_order,created_at,updated_at) VALUES(?,1,?,?,?) "
                    "ON CONFLICT(code) DO UPDATE SET active=1, sort_order=excluded.sort_order, updated_at=excluded.updated_at",
                    (code, order, ts, ts),
                )

    def record_payment_only(self, server_id: int, amount_minor: int, currency: str, due_date: str, note: str = "") -> int:
        server = self.get_server(server_id)
        if not server:
            raise ValueError("Сервер не найден")
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO payments(server_id,amount_minor,currency,due_date,paid_at,next_due,note) VALUES(?,?,?,?,?,?,?)",
                (server_id, amount_minor, currency, due_date, now_iso(), server["next_due"], note),
            )
            return int(cur.lastrowid)

    def get_server(self, server_id: int) -> dict | None:
        with self.conn() as c:
            return self._row(c.execute("SELECT * FROM servers WHERE id=?", (server_id,)).fetchone())

    def update_due(self, server_id: int, next_due: str) -> None:
        with self.conn() as c:
            c.execute("UPDATE servers SET next_due=?, updated_at=? WHERE id=?", (next_due, now_iso(), server_id))

    def update_server_field(self, server_id: int, field: str, value: str) -> None:
        allowed = {"name", "ip", "country", "purpose", "tags", "notes"}
        if field not in allowed:
            raise ValueError("Недопустимое поле")
        value = (value or "").strip()
        if field == "tags":
            parts = []
            seen = set()
            for raw in value.replace("#", "").replace(";", ",").split(","):
                tag = " ".join(raw.strip().split())
                if tag and tag.casefold() not in seen:
                    seen.add(tag.casefold())
                    parts.append(tag[:32])
            value = ",".join(parts[:12])
        with self.conn() as c:
            c.execute(f"UPDATE servers SET {field}=?, updated_at=? WHERE id=?", (value, now_iso(), server_id))

    def trash_server(self, server_id: int) -> None:
        with self.conn() as c:
            c.execute("UPDATE servers SET active=0, archived_at=NULL, deleted_at=?, updated_at=? WHERE id=?", (now_iso(), now_iso(), server_id))
            c.execute("DELETE FROM snoozes WHERE server_id=?", (server_id,))

    def restore_server(self, server_id: int) -> None:
        with self.conn() as c:
            c.execute("UPDATE servers SET active=1, deleted_at=NULL, archived_at=NULL, updated_at=? WHERE id=?", (now_iso(), server_id))

    def archive_server(self, server_id: int) -> None:
        with self.conn() as c:
            c.execute("UPDATE servers SET active=0, archived_at=?, deleted_at=NULL, monitor_enabled=0, updated_at=? WHERE id=?", (now_iso(), now_iso(), server_id))
            c.execute("DELETE FROM snoozes WHERE server_id=?", (server_id,))

    def restore_archived_server(self, server_id: int) -> None:
        with self.conn() as c:
            c.execute("UPDATE servers SET active=1, archived_at=NULL, updated_at=? WHERE id=?", (now_iso(), server_id))

    def list_archive(self) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("SELECT * FROM servers WHERE archived_at IS NOT NULL AND deleted_at IS NULL ORDER BY datetime(archived_at) DESC").fetchall()
        return [dict(r) for r in rows]

    def archive_count(self) -> int:
        with self.conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM servers WHERE archived_at IS NOT NULL AND deleted_at IS NULL").fetchone()[0])

    def archive_to_trash(self, server_id: int) -> None:
        with self.conn() as c:
            c.execute("UPDATE servers SET active=0, archived_at=NULL, deleted_at=?, updated_at=? WHERE id=?", (now_iso(), now_iso(), server_id))

    def purge_server(self, server_id: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM servers WHERE id=? AND deleted_at IS NOT NULL", (server_id,))

    def purge_all_trash(self) -> int:
        with self.conn() as c:
            count = int(c.execute("SELECT COUNT(*) FROM servers WHERE deleted_at IS NOT NULL").fetchone()[0])
            c.execute("DELETE FROM servers WHERE deleted_at IS NOT NULL")
        return count

    def list_trash(self) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("SELECT * FROM servers WHERE deleted_at IS NOT NULL ORDER BY datetime(deleted_at) DESC").fetchall()
        return [dict(r) for r in rows]

    def trash_count(self) -> int:
        with self.conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM servers WHERE deleted_at IS NOT NULL").fetchone()[0])

    def list_tags(self) -> list[str]:
        tags: dict[str, str] = {}
        for server in self.list_servers():
            for raw in str(server.get("tags") or "").split(","):
                tag = raw.strip()
                if tag:
                    tags.setdefault(tag.casefold(), tag)
        return sorted(tags.values(), key=str.casefold)

    def add_payment(self, server_id: int, amount_minor: int, currency: str, due_date: str, next_due: str, note: str = "") -> int:
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO payments(server_id,amount_minor,currency,due_date,paid_at,next_due,note) VALUES(?,?,?,?,?,?,?)",
                (server_id, amount_minor, currency, due_date, now_iso(), next_due, note),
            )
            c.execute("UPDATE servers SET next_due=?,updated_at=? WHERE id=?", (next_due, now_iso(), server_id))
            c.execute("DELETE FROM snoozes WHERE server_id=?", (server_id,))
            return int(cur.lastrowid)

    def add_payment_atomic(self, server_id: int, expected_due: str, amount_minor: int, currency: str, next_due: str, note: str = "") -> tuple[bool, dict | None]:
        """Atomically pay exactly one expected billing period.

        Returns (paid, server_after). If next_due has already changed, no second
        payment is created. This protects against double taps and stale buttons.
        """
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=30000")
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM servers WHERE id=?", (server_id,)).fetchone()
            if not row or row["deleted_at"] is not None or str(row["next_due"]) != str(expected_due):
                c.execute("ROLLBACK")
                return False, dict(row) if row else None
            ts = now_iso()
            c.execute(
                "INSERT INTO payments(server_id,amount_minor,currency,due_date,paid_at,next_due,note) VALUES(?,?,?,?,?,?,?)",
                (server_id, int(amount_minor), str(currency), str(expected_due), ts, str(next_due), note),
            )
            cur = c.execute(
                "UPDATE servers SET next_due=?,updated_at=? WHERE id=? AND next_due=?",
                (str(next_due), ts, server_id, str(expected_due)),
            )
            if cur.rowcount != 1:
                c.execute("ROLLBACK")
                return False, dict(row)
            c.execute("DELETE FROM snoozes WHERE server_id=?", (server_id,))
            c.execute("COMMIT")
            row2 = c.execute("SELECT * FROM servers WHERE id=?", (server_id,)).fetchone()
            return True, dict(row2) if row2 else None
        except Exception:
            try:
                c.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            c.close()

    def recent_payments(self, limit: int = 30) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT p.*, s.name, s.provider FROM payments p JOIN servers s ON s.id=p.server_id ORDER BY datetime(p.paid_at) DESC LIMIT ?",
                (limit,),
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
            rows = c.execute(
                "SELECT * FROM servers WHERE active=1 AND deleted_at IS NULL AND date(next_due)>=date(?) AND date(next_due)<=date(?) ORDER BY date(next_due)",
                (start_date, end_date),
            ).fetchall()
            return [dict(r) for r in rows]

    def notification_sent(self, server_id: int, due_date: str, kind: str) -> bool:
        with self.conn() as c:
            return c.execute(
                "SELECT 1 FROM notification_log WHERE server_id=? AND due_date=? AND kind=?",
                (server_id, due_date, kind),
            ).fetchone() is not None

    def mark_notification(self, server_id: int, due_date: str, kind: str) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO notification_log(server_id,due_date,kind,sent_at) VALUES(?,?,?,?)",
                (server_id, due_date, kind, now_iso()),
            )

    def snooze_until(self, server_id: int, until_at: str) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO snoozes(server_id,until_at) VALUES(?,?) ON CONFLICT(server_id) DO UPDATE SET until_at=excluded.until_at",
                (server_id, until_at),
            )

    def is_snoozed(self, server_id: int, now_value: str) -> bool:
        with self.conn() as c:
            row = c.execute("SELECT until_at FROM snoozes WHERE server_id=?", (server_id,)).fetchone()
        return bool(row and row[0] > now_value)

    def due_snoozes(self, now_value: str) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT s.*, z.until_at FROM snoozes z JOIN servers s ON s.id=z.server_id WHERE s.active=1 AND s.deleted_at IS NULL AND z.until_at<=? ORDER BY z.until_at",
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

    def get_setting(self, key: str, default: str = "") -> str:
        with self.conn() as c:
            row = c.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, value, now_iso()),
            )

    def get_reminder_days(self) -> tuple[int, ...]:
        raw = self.get_setting("reminder_days", DEFAULT_SETTINGS["reminder_days"])
        vals = []
        for part in raw.split(","):
            part = part.strip()
            if part:
                try:
                    vals.append(int(part))
                except ValueError:
                    pass
        return tuple(sorted(set(vals), reverse=True))

    def set_reminder_days(self, days: list[int] | tuple[int, ...]) -> None:
        cleaned = sorted({int(x) for x in days if int(x) >= 0}, reverse=True)
        self.set_setting("reminder_days", ",".join(str(x) for x in cleaned))


    def get_billing_cycles(self) -> tuple[str, ...]:
        allowed = ("daily", "weekly", "monthly", "quarterly", "semiannual", "yearly")
        raw = self.get_setting("billing_cycles", DEFAULT_SETTINGS["billing_cycles"])
        selected = {part.strip() for part in raw.split(",") if part.strip() in allowed}
        # Preserve a stable, user-friendly order independent of DB text ordering.
        ordered = tuple(c for c in allowed if c in selected)
        return ordered or ("weekly", "monthly", "quarterly", "yearly")

    def set_billing_cycles(self, cycles: list[str] | tuple[str, ...]) -> None:
        allowed = ("daily", "weekly", "monthly", "quarterly", "semiannual", "yearly")
        selected = {str(c).strip() for c in cycles if str(c).strip() in allowed}
        ordered = [c for c in allowed if c in selected]
        # Never allow an empty creation menu.
        if not ordered:
            ordered = ["weekly", "monthly", "quarterly", "yearly"]
        self.set_setting("billing_cycles", ",".join(ordered))

    def overdue_daily(self) -> bool:
        return self.get_setting("overdue_daily", "1") == "1"

    def monthly_report_enabled(self) -> bool:
        return self.get_setting("monthly_report_enabled", "1") == "1"

    def report_day(self) -> int:
        try:
            return max(1, min(28, int(self.get_setting("report_day", "1"))))
        except ValueError:
            return 1

    def report_hour(self) -> int:
        try:
            return max(0, min(23, int(self.get_setting("report_hour", "10"))))
        except ValueError:
            return 10

    def report_minute(self) -> int:
        try:
            return max(0, min(59, int(self.get_setting("report_minute", "0"))))
        except ValueError:
            return 0

    def set_report_time(self, value: str) -> None:
        raw = str(value or "").strip()
        try:
            hh, mm = raw.split(":", 1)
            hour = int(hh); minute = int(mm)
        except Exception as exc:
            raise ValueError("Время должно быть в формате ЧЧ:ММ") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Время должно быть в формате ЧЧ:ММ")
        self.set_setting("report_hour", str(hour))
        self.set_setting("report_minute", str(minute))



    def payment_reminder_time(self) -> str:
        raw = str(self.get_setting("payment_reminder_time", "10:00") or "10:00").strip()
        try:
            hh, mm = raw.split(":", 1)
            hour = max(0, min(23, int(hh)))
            minute = max(0, min(59, int(mm)))
            return f"{hour:02d}:{minute:02d}"
        except Exception:
            return "10:00"

    def set_payment_reminder_time(self, value: str) -> None:
        raw = str(value or "").strip()
        try:
            hh, mm = raw.split(":", 1)
            hour = int(hh); minute = int(mm)
        except Exception as exc:
            raise ValueError("Время должно быть в формате ЧЧ:ММ") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Время должно быть в формате ЧЧ:ММ")
        self.set_setting("payment_reminder_time", f"{hour:02d}:{minute:02d}")

    def auto_update_enabled(self) -> bool:
        return self.get_setting("auto_update_enabled", "0") == "1"

    def set_auto_update_enabled(self, enabled: bool) -> None:
        self.set_setting("auto_update_enabled", "1" if enabled else "0")

    def auto_update_manifest_url(self) -> str:
        return str(self.get_setting("auto_update_manifest_url", "") or "").strip()

    def set_auto_update_manifest_url(self, value: str) -> None:
        self.set_setting("auto_update_manifest_url", str(value or "").strip())

    def update_check_enabled(self) -> bool:
        return self.get_setting("update_check_enabled", "1") == "1"

    def set_update_check_enabled(self, enabled: bool) -> None:
        self.set_setting("update_check_enabled", "1" if enabled else "0")

    def update_last_check_day(self) -> str:
        return str(self.get_setting("update_last_check_day", "") or "")

    def set_update_last_check_day(self, value: str) -> None:
        self.set_setting("update_last_check_day", str(value or ""))

    def update_last_offered(self) -> str:
        return str(self.get_setting("update_last_offered", "") or "")

    def set_update_last_offered(self, value: str) -> None:
        self.set_setting("update_last_offered", str(value or ""))

    def update_remind_after(self) -> str:
        return str(self.get_setting("update_remind_after", "") or "")

    def set_update_remind_after(self, value: str) -> None:
        self.set_setting("update_remind_after", str(value or ""))

    def update_ignored_version(self) -> str:
        return str(self.get_setting("update_ignored_version", "") or "")

    def set_update_ignored_version(self, value: str) -> None:
        self.set_setting("update_ignored_version", str(value or ""))

    def update_result_notified(self) -> str:
        return str(self.get_setting("update_result_notified", "") or "")

    def set_update_result_notified(self, value: str) -> None:
        self.set_setting("update_result_notified", str(value or ""))

    def backup_keep_days(self) -> int:
        try: return max(1, min(3650, int(self.get_setting("backup_keep_days", "30"))))
        except ValueError: return 30

    def backup_keep_count(self) -> int:
        try: return max(3, min(500, int(self.get_setting("backup_keep_count", "30"))))
        except ValueError: return 30

    def provider_url(self, provider: str) -> str:
        name = " ".join(str(provider or "").strip().split())
        if not name:
            return ""
        with self.conn() as c:
            row = c.execute("SELECT cabinet_url FROM provider_settings WHERE provider=? COLLATE NOCASE", (name,)).fetchone()
        return str(row["cabinet_url"] or "") if row else ""

    @staticmethod
    def normalize_provider_url(url: str) -> str:
        value = str(url or "").strip()
        if not value:
            return ""
        if value.startswith("@"):
            username = value[1:].strip()
            if not username or any(ch.isspace() for ch in username):
                raise ValueError("Некорректное имя Telegram-бота")
            return f"https://t.me/{username}"
        if value.startswith("t.me/"):
            value = "https://" + value
        elif value.startswith("telegram.me/"):
            value = "https://" + value
        if value.startswith(("https://", "http://")):
            return value
        raise ValueError("Укажи https://сайт, t.me/бота или @имя_бота")

    def set_provider_url(self, provider: str, url: str) -> None:
        name = " ".join(str(provider or "").strip().split())
        if not name:
            raise ValueError("Хостер не указан")
        value = self.normalize_provider_url(url)
        with self.conn() as c:
            if value:
                c.execute(
                    "INSERT INTO provider_settings(provider,cabinet_url,updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(provider) DO UPDATE SET cabinet_url=excluded.cabinet_url, updated_at=excluded.updated_at",
                    (name, value, now_iso()),
                )
            else:
                c.execute("DELETE FROM provider_settings WHERE provider=? COLLATE NOCASE", (name,))

    def monitoring_enabled(self) -> bool:
        return self.get_setting("monitoring_enabled", "0") == "1"

    def monitor_interval(self) -> int:
        try:
            return max(30, min(1800, int(self.get_setting("monitor_interval", "180"))))
        except ValueError:
            return 180

    def monitor_failures(self) -> int:
        try:
            return max(1, min(10, int(self.get_setting("monitor_failures", "3"))))
        except ValueError:
            return 3

    def monitor_recovery(self) -> int:
        try:
            return max(1, min(10, int(self.get_setting("monitor_recovery", "2"))))
        except ValueError:
            return 2

    def monitor_timeout(self) -> int:
        try:
            return max(1, min(10, int(self.get_setting("monitor_timeout", "3"))))
        except ValueError:
            return 3

    def monitor_method(self) -> str:
        value = str(self.get_setting("monitor_method", "auto") or "auto").strip().lower()
        return value if value in {"auto", "ping", "tcp"} else "auto"

    def monitor_tcp_port(self) -> int:
        try:
            return max(1, min(65535, int(self.get_setting("monitor_tcp_port", "22"))))
        except ValueError:
            return 22


    def used_countries(self) -> list[str]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT country, COUNT(*) AS cnt FROM servers WHERE deleted_at IS NULL AND trim(country)<>'' GROUP BY country ORDER BY cnt DESC, lower(country) ASC"
            ).fetchall()
        return [str(r["country"]).strip() for r in rows if str(r["country"] or "").strip()]


    def rename_provider(self, old: str, new: str) -> int:
        old = " ".join(str(old).strip().split())
        new = " ".join(str(new).strip().split())[:80]
        if not old or not new:
            raise ValueError("Название не может быть пустым")
        with self.conn() as c:
            cur = c.execute(
                "UPDATE servers SET provider=?, updated_at=? WHERE lower(trim(provider))=lower(trim(?))",
                (new, datetime.now(timezone.utc).isoformat(), old),
            )
            link = c.execute("SELECT cabinet_url FROM provider_settings WHERE provider=? COLLATE NOCASE", (old,)).fetchone()
            target_link = c.execute("SELECT cabinet_url FROM provider_settings WHERE provider=? COLLATE NOCASE", (new,)).fetchone()
            if link:
                c.execute("DELETE FROM provider_settings WHERE provider=? COLLATE NOCASE", (old,))
                # If the target provider already has its own LK URL, preserve it.
                if not target_link or not str(target_link["cabinet_url"] or "").strip():
                    c.execute(
                        "INSERT INTO provider_settings(provider,cabinet_url,updated_at) VALUES(?,?,?) "
                        "ON CONFLICT(provider) DO UPDATE SET cabinet_url=excluded.cabinet_url, updated_at=excluded.updated_at",
                        (new, str(link["cabinet_url"] or ""), now_iso()),
                    )
            c.commit()
            return int(cur.rowcount or 0)

    def rename_country(self, old: str, new: str) -> int:
        old = " ".join(str(old).strip().split())
        new = " ".join(str(new).strip().split())[:80]
        if not old or not new:
            raise ValueError("Название не может быть пустым")
        with self.conn() as c:
            cur = c.execute(
                "UPDATE servers SET country=?, updated_at=? WHERE lower(trim(country))=lower(trim(?))",
                (new, datetime.now(timezone.utc).isoformat(), old),
            )
            c.commit()
            return int(cur.rowcount or 0)

    def rename_tag(self, old: str, new: str) -> int:
        old = " ".join(str(old).replace("#", "").strip().split())
        new = " ".join(str(new).replace("#", "").strip().split())[:32]
        if not old or not new:
            raise ValueError("Тег не может быть пустым")
        changed = 0
        now = datetime.now(timezone.utc).isoformat()
        with self.conn() as c:
            rows = c.execute("SELECT id,tags FROM servers WHERE deleted_at IS NULL AND trim(tags)<>''").fetchall()
            for row in rows:
                tags = [x.strip() for x in str(row["tags"] or "").split(",") if x.strip()]
                if not any(x.casefold() == old.casefold() for x in tags):
                    continue
                out=[]
                seen=set()
                for tag in tags:
                    value = new if tag.casefold() == old.casefold() else tag
                    key=value.casefold()
                    if key not in seen:
                        seen.add(key); out.append(value)
                c.execute("UPDATE servers SET tags=?, updated_at=? WHERE id=?", (",".join(out), now, int(row["id"])))
                changed += 1
            c.commit()
        return changed

    def used_tags(self) -> list[str]:
        counts: dict[str, int] = {}
        names: dict[str, str] = {}
        with self.conn() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT tags FROM servers WHERE deleted_at IS NULL AND trim(tags)<>''"
            ).fetchall()]
        for row in rows:
            for raw in str(row.get("tags") or "").split(","):
                tag = raw.strip()
                if not tag:
                    continue
                key = tag.casefold()
                counts[key] = counts.get(key, 0) + 1
                names.setdefault(key, tag)
        return [names[k] for k in sorted(counts, key=lambda x: (-counts[x], names[x].casefold()))]

    def servers_with_country(self, country: str) -> list[dict]:
        country = " ".join(str(country).strip().split())
        with self.conn() as c:
            rows = c.execute(
                "SELECT id,name,archived_at FROM servers "
                "WHERE deleted_at IS NULL AND lower(trim(country))=lower(trim(?)) "
                "ORDER BY lower(name)",
                (country,),
            ).fetchall()
        return [dict(r) for r in rows]

    def servers_with_tag(self, tag: str) -> list[dict]:
        tag = " ".join(str(tag).replace("#", "").strip().split())
        result: list[dict] = []
        with self.conn() as c:
            rows = c.execute(
                "SELECT id,name,tags,archived_at FROM servers "
                "WHERE deleted_at IS NULL AND trim(tags)<>'' ORDER BY lower(name)"
            ).fetchall()
        for row in rows:
            tags = [x.strip() for x in str(row["tags"] or "").split(",") if x.strip()]
            if any(x.casefold() == tag.casefold() for x in tags):
                result.append(dict(row))
        return result

    def delete_country(self, country: str) -> int:
        country = " ".join(str(country).strip().split())
        if not country:
            raise ValueError("Страна не задана")
        with self.conn() as c:
            cur = c.execute(
                "UPDATE servers SET country='', updated_at=? "
                "WHERE deleted_at IS NULL AND lower(trim(country))=lower(trim(?))",
                (datetime.now(timezone.utc).isoformat(), country),
            )
            c.commit()
            return int(cur.rowcount or 0)

    def delete_tag(self, tag: str) -> int:
        tag = " ".join(str(tag).replace("#", "").strip().split())
        if not tag:
            raise ValueError("Тег не задан")
        changed = 0
        now = datetime.now(timezone.utc).isoformat()
        with self.conn() as c:
            rows = c.execute(
                "SELECT id,tags FROM servers WHERE deleted_at IS NULL AND trim(tags)<>''"
            ).fetchall()
            for row in rows:
                tags = [x.strip() for x in str(row["tags"] or "").split(",") if x.strip()]
                kept = [x for x in tags if x.casefold() != tag.casefold()]
                if len(kept) == len(tags):
                    continue
                c.execute(
                    "UPDATE servers SET tags=?, updated_at=? WHERE id=?",
                    (",".join(kept), now, int(row["id"])),
                )
                changed += 1
            c.commit()
        return changed

    def toggle_server_tag(self, server_id: int, tag: str) -> bool:
        server = self.get_server(server_id)
        if not server:
            raise ValueError("Сервер не найден")
        tag = " ".join(str(tag).replace("#", "").strip().split())[:32]
        if not tag:
            raise ValueError("Пустой тег")
        tags = [x.strip() for x in str(server.get("tags") or "").split(",") if x.strip()]
        exists = next((x for x in tags if x.casefold() == tag.casefold()), None)
        if exists:
            tags = [x for x in tags if x.casefold() != tag.casefold()]
            active = False
        else:
            tags.append(tag)
            active = True
        self.update_server_field(server_id, "tags", ",".join(tags))
        return active

    def add_server_tag(self, server_id: int, tag: str) -> None:
        server = self.get_server(server_id)
        if not server:
            raise ValueError("Сервер не найден")
        tag = " ".join(str(tag).replace("#", "").strip().split())[:32]
        tags = [x.strip() for x in str(server.get("tags") or "").split(",") if x.strip()]
        if tag and all(x.casefold() != tag.casefold() for x in tags):
            tags.append(tag)
        self.update_server_field(server_id, "tags", ",".join(tags))

    def balance_remaining_minor(self, server: dict, on_date: date | None = None) -> int:
        if str(server.get("billing_mode") or "scheduled") != "balance":
            return int(server.get("balance_minor") or 0)
        on_date = on_date or date.today()
        asof_raw = server.get("balance_updated_at")
        try:
            asof = date.fromisoformat(str(asof_raw)[:10]) if asof_raw else on_date
        except ValueError:
            asof = on_date
        elapsed = max(0, (on_date - asof).days)
        return max(0, int(server.get("balance_minor") or 0) - elapsed * int(server.get("amount_minor") or 0))

    def topup_balance(self, server_id: int, amount_minor: int) -> int:
        server = self.get_server(server_id)
        if not server or str(server.get("billing_mode") or "") != "balance":
            raise ValueError("Сервер не использует оплату с баланса")
        remaining = self.balance_remaining_minor(server)
        new_balance = remaining + int(amount_minor)
        today = date.today()
        stamp = now_iso()
        days_left = new_balance // max(1, int(server.get("amount_minor") or 1))
        estimated_due = date.fromordinal(today.toordinal() + days_left).isoformat()
        with self.conn() as c:
            c.execute("UPDATE servers SET balance_minor=?, balance_updated_at=?, next_due=?, updated_at=? WHERE id=?", (new_balance, stamp, estimated_due, stamp, server_id))
        self.record_payment_only(server_id, int(amount_minor), server["currency"], today.isoformat(), note="Пополнение баланса")
        return new_balance

    def enable_monitoring_for_all_with_ip(self) -> tuple[int, int]:
        with self.conn() as c:
            total = int(c.execute("SELECT COUNT(*) FROM servers WHERE active=1 AND deleted_at IS NULL AND trim(ip)<>''").fetchone()[0])
            already = int(c.execute("SELECT COUNT(*) FROM servers WHERE active=1 AND deleted_at IS NULL AND trim(ip)<>'' AND monitor_enabled=1").fetchone()[0])
            c.execute("UPDATE servers SET monitor_enabled=1, updated_at=? WHERE active=1 AND deleted_at IS NULL AND trim(ip)<>''", (now_iso(),))
        return total, already

    def monitoring_all_state(self) -> tuple[str, int, int]:
        """Return (state, total_with_ip, monitored_with_ip)."""
        with self.conn() as c:
            total = int(c.execute("SELECT COUNT(*) FROM servers WHERE active=1 AND deleted_at IS NULL AND trim(ip)<>''").fetchone()[0])
            monitored = int(c.execute("SELECT COUNT(*) FROM servers WHERE active=1 AND deleted_at IS NULL AND trim(ip)<>'' AND monitor_enabled=1").fetchone()[0])
        if total == 0:
            return "none", 0, 0
        if monitored == 0:
            return "off", total, monitored
        if monitored == total:
            return "on", total, monitored
        return "partial", total, monitored

    def monitored_servers(self) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("SELECT * FROM servers WHERE active=1 AND deleted_at IS NULL AND monitor_enabled=1 AND trim(ip)<>'' ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def toggle_server_monitoring(self, server_id: int) -> bool:
        with self.conn() as c:
            row = c.execute("SELECT ip,monitor_enabled FROM servers WHERE id=? AND deleted_at IS NULL", (server_id,)).fetchone()
            if not row:
                raise ValueError("Сервер не найден")
            if not str(row["ip"] or "").strip():
                raise ValueError("Сначала укажите IP")
            value = 0 if bool(row["monitor_enabled"]) else 1
            c.execute("UPDATE servers SET monitor_enabled=?, updated_at=? WHERE id=?", (value, now_iso(), server_id))
            if not value:
                c.execute("DELETE FROM monitor_state WHERE server_id=?", (server_id,))
            return bool(value)

    def down_monitored_servers(self) -> list[dict]:
        """Active monitored servers currently confirmed DOWN."""
        with self.conn() as c:
            rows = c.execute(
                "SELECT s.* FROM servers s "
                "JOIN monitor_state m ON m.server_id=s.id "
                "WHERE s.deleted_at IS NULL AND s.monitor_enabled=1 "
                "AND trim(COALESCE(s.ip,''))<>'' AND m.is_down=1 "
                "ORDER BY lower(s.name), s.id"
            ).fetchall()
        return [dict(r) for r in rows]

    def monitor_state(self, server_id: int) -> dict:
        with self.conn() as c:
            row = c.execute("SELECT * FROM monitor_state WHERE server_id=?", (server_id,)).fetchone()
        return dict(row) if row else {"server_id": server_id, "is_down": 0, "fail_count": 0, "success_count": 0, "last_check": None, "last_change": None}

    def update_monitor_result(self, server_id: int, ok: bool) -> tuple[bool, str | None]:
        """Return (is_down, transition) where transition is 'down', 'up', or None."""
        st = self.monitor_state(server_id)
        was_down = bool(st.get("is_down"))
        fails = int(st.get("fail_count") or 0)
        successes = int(st.get("success_count") or 0)
        transition = None
        if ok:
            fails = 0
            successes += 1
            is_down = was_down
            if was_down and successes >= self.monitor_recovery():
                is_down = False
                transition = "up"
                successes = 0
        else:
            successes = 0
            fails += 1
            is_down = was_down
            if not was_down and fails >= self.monitor_failures():
                is_down = True
                transition = "down"
                fails = 0
        ts = now_iso()
        with self.conn() as c:
            c.execute(
                "INSERT INTO monitor_state(server_id,is_down,fail_count,success_count,last_check,last_change) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(server_id) DO UPDATE SET is_down=excluded.is_down, fail_count=excluded.fail_count, success_count=excluded.success_count, last_check=excluded.last_check, last_change=CASE WHEN excluded.is_down<>monitor_state.is_down THEN excluded.last_check ELSE monitor_state.last_change END",
                (server_id, 1 if is_down else 0, fails, successes, ts, ts if transition else st.get("last_change")),
            )
        return bool(is_down), transition

    def enqueue_outbox(self, event_key: str, kind: str, text: str, *, server_id: int | None = None, due_date: str | None = None) -> bool:
        with self.conn() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO outbox(event_key,kind,server_id,due_date,text,created_at,next_attempt_at) VALUES(?,?,?,?,?,?,?)",
                (event_key, kind, server_id, due_date, text, now_iso(), now_iso()),
            )
            return bool(cur.rowcount)

    def outbox_exists(self, event_key: str) -> bool:
        with self.conn() as c:
            return c.execute("SELECT 1 FROM outbox WHERE event_key=?", (event_key,)).fetchone() is not None

    def pending_outbox(self, limit: int = 50) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT * FROM outbox WHERE sent_at IS NULL AND (next_attempt_at IS NULL OR datetime(next_attempt_at)<=datetime(?)) ORDER BY id LIMIT ?",
                (now_iso(), int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_outbox_sent(self, event_id: int) -> None:
        with self.conn() as c:
            c.execute("UPDATE outbox SET sent_at=?, last_error='' WHERE id=?", (now_iso(), int(event_id)))

    def mark_outbox_failed(self, event_id: int, error: str, retry_seconds: int = 60) -> None:
        from datetime import timedelta
        nxt = (datetime.now().astimezone() + timedelta(seconds=max(30, int(retry_seconds)))).isoformat(timespec="seconds")
        with self.conn() as c:
            c.execute(
                "UPDATE outbox SET attempts=attempts+1,last_error=?,next_attempt_at=? WHERE id=?",
                (str(error)[:1000], nxt, int(event_id)),
            )

    def set_runtime(self, key: str, value: str) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO runtime_state(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                (key, str(value), now_iso()),
            )

    def get_runtime(self, key: str) -> dict | None:
        with self.conn() as c:
            row = c.execute("SELECT key,value,updated_at FROM runtime_state WHERE key=?", (key,)).fetchone()
        return dict(row) if row else None

    def get_emojis(self) -> dict[str, str]:
        # Project defaults are always available. Per-installation values in
        # SQLite override them without modifying the release files.
        result = dict(DEFAULT_CUSTOM_EMOJIS)
        with self.conn() as c:
            rows = c.execute("SELECT slot, custom_emoji_id FROM emoji_settings WHERE custom_emoji_id<>''").fetchall()
        result.update({str(r["slot"]): str(r["custom_emoji_id"]) for r in rows})
        return result

    def set_emoji(self, slot: str, custom_emoji_id: str | None) -> None:
        value = (custom_emoji_id or "").strip()
        with self.conn() as c:
            c.execute(
                "INSERT INTO emoji_settings(slot,custom_emoji_id,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(slot) DO UPDATE SET custom_emoji_id=excluded.custom_emoji_id, updated_at=excluded.updated_at",
                (slot, value, now_iso()),
            )

    def clear_all_emojis(self) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM emoji_settings")
