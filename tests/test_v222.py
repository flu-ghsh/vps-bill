from app.db import Database


def test_monthly_report_day_defaults_and_clamps(tmp_path):
    db = Database(tmp_path / "billing.db")
    assert db.report_day() == 1
    db.set_setting("report_day", "15")
    assert db.report_day() == 15
    db.set_setting("report_day", "31")
    assert db.report_day() == 28
    db.set_setting("report_day", "bad")
    assert db.report_day() == 1
