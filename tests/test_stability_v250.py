from datetime import date, timedelta
from pathlib import Path

from app.billing import next_due
from app.db import Database


def make_db(tmp_path: Path) -> Database:
    return Database(tmp_path / "billing.db")


def test_atomic_payment_rejects_double_tap(tmp_path):
    db = make_db(tmp_path)
    due = date.today().isoformat()
    sid = db.add_server(
        name="node", provider="host", amount_minor=10000, currency="RUB",
        next_due=due, cycle="monthly"
    )
    nd = next_due(due, "monthly", None)
    ok1, _ = db.add_payment_atomic(sid, due, 10000, "RUB", nd)
    ok2, _ = db.add_payment_atomic(sid, due, 10000, "RUB", nd)
    assert ok1 is True
    assert ok2 is False
    assert len(db.recent_payments(10)) == 1


def test_outbox_is_deduplicated_and_persistent(tmp_path):
    db = make_db(tmp_path)
    assert db.enqueue_outbox("event:1", "monthly", "hello") is True
    assert db.enqueue_outbox("event:1", "monthly", "hello again") is False
    rows = db.pending_outbox()
    assert len(rows) == 1
    assert rows[0]["text"] == "hello"
    db.mark_outbox_sent(rows[0]["id"])
    assert db.pending_outbox() == []
    assert db.outbox_exists("event:1") is True


def test_new_install_monitoring_defaults_are_safe(tmp_path):
    db = make_db(tmp_path)
    assert db.monitoring_enabled() is False
    assert db.monitor_interval() == 180
    assert db.monitor_failures() == 3
    assert db.monitor_recovery() == 2


def test_runtime_heartbeat_roundtrip(tmp_path):
    db = make_db(tmp_path)
    db.set_runtime("notifier_heartbeat", "ok")
    row = db.get_runtime("notifier_heartbeat")
    assert row and row["value"] == "ok"
