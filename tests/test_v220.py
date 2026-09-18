import sqlite3
from pathlib import Path

from app.db import Database, SCHEMA_VERSION


def test_rich_fields_trash_restore_and_tags(tmp_path: Path):
    db = Database(tmp_path / "billing.db")
    sid = db.add_server(
        name="node-fi",
        provider="Hoster",
        amount_minor=999,
        currency="EUR",
        next_due="2026-09-20",
        cycle="monthly",
    )
    db.update_server_field(sid, "ip", "10.0.0.1")
    db.update_server_field(sid, "tags", "VPN, prod, #vpn, telegram")
    row = db.get_server(sid)
    assert row["ip"] == "10.0.0.1"
    assert row["tags"] == "VPN,prod,telegram"
    assert db.list_tags() == ["prod", "telegram", "VPN"]

    db.trash_server(sid)
    assert db.list_servers() == []
    assert db.trash_count() == 1
    assert db.get_server(sid)["deleted_at"]

    db.restore_server(sid)
    assert len(db.list_servers()) == 1
    assert db.trash_count() == 0


def test_v21_database_is_migrated_additively(tmp_path: Path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE servers (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          provider TEXT NOT NULL DEFAULT '',
          category TEXT NOT NULL DEFAULT 'VPS',
          amount_minor INTEGER NOT NULL,
          currency TEXT NOT NULL DEFAULT 'RUB',
          cycle TEXT NOT NULL DEFAULT 'monthly',
          cycle_days INTEGER,
          next_due TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1,
          notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        INSERT INTO servers(name,provider,amount_minor,currency,cycle,next_due,created_at,updated_at)
        VALUES('legacy','OldHost',10000,'RUB','monthly','2026-10-01','2026-01-01','2026-01-01');
        """
    )
    conn.commit()
    conn.close()

    db = Database(path)
    row = db.list_servers()[0]
    assert row["name"] == "legacy"
    assert row["ip"] == ""
    assert row["tags"] == ""
    assert row["deleted_at"] is None
    assert db.integrity()["schema_version"] == SCHEMA_VERSION
