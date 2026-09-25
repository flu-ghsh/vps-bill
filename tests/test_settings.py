from pathlib import Path

from app.db import Database


def test_default_billing_cycles(tmp_path: Path):
    db = Database(tmp_path / "billing.db")
    assert db.get_billing_cycles() == ("weekly", "monthly", "quarterly", "yearly")


def test_billing_cycles_are_stored_and_empty_is_safe(tmp_path: Path):
    db = Database(tmp_path / "billing.db")
    db.set_billing_cycles(("daily", "semiannual"))
    assert db.get_billing_cycles() == ("daily", "semiannual")
    db.set_billing_cycles(())
    assert db.get_billing_cycles() == ("weekly", "monthly", "quarterly", "yearly")
