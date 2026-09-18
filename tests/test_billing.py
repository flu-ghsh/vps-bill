from datetime import date
from app.billing import next_due, parse_amount_minor, parse_date, days_until


def test_amount():
    assert parse_amount_minor("15.90") == 1590
    assert parse_amount_minor("1 490,00") == 149000


def test_dates():
    assert parse_date("25.09.2026").isoformat() == "2026-09-25"
    assert next_due("2026-01-31", "monthly") == "2026-02-28"
    assert next_due("2024-02-29", "yearly") == "2025-02-28"
    assert days_until("2026-09-20", date(2026,9,18)) == 2
