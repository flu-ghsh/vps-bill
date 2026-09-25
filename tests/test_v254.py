from pathlib import Path

from app.db import Database


def test_provider_cabinet_url_roundtrip_and_rename(tmp_path: Path):
    db = Database(tmp_path / "billing.db")
    db.add_server(
        name="node", provider="Weasel.cloud", amount_minor=21500,
        currency="RUB", next_due="2026-09-22", cycle="monthly"
    )
    db.set_provider_url("Weasel.cloud", "https://example.com/lk")
    assert db.provider_url("weasel.cloud") == "https://example.com/lk"
    assert db.rename_provider("Weasel.cloud", "Weasel Cloud") == 1
    assert db.provider_url("Weasel.cloud") == ""
    assert db.provider_url("Weasel Cloud") == "https://example.com/lk"


def test_provider_url_validation_and_clear(tmp_path: Path):
    db = Database(tmp_path / "billing.db")
    try:
        db.set_provider_url("Host", "example.com")
        assert False, "URL without scheme must be rejected"
    except ValueError:
        pass
    db.set_provider_url("Host", "https://example.com")
    db.set_provider_url("Host", "")
    assert db.provider_url("Host") == ""


def test_payment_reminder_time_defaults_and_validation(tmp_path: Path):
    db = Database(tmp_path / "billing.db")
    assert db.payment_reminder_time() == "10:00"
    db.set_payment_reminder_time("08:35")
    assert db.payment_reminder_time() == "08:35"
    try:
        db.set_payment_reminder_time("24:00")
        assert False, "invalid time must fail"
    except ValueError:
        pass


def test_report_time_supports_minutes(tmp_path: Path):
    db = Database(tmp_path / "billing.db")
    assert db.report_hour() == 10
    assert db.report_minute() == 0
    db.set_report_time("21:45")
    assert db.report_hour() == 21
    assert db.report_minute() == 45


def test_v254_ui_text_and_no_progress_bars():
    root = Path(__file__).parents[1]
    ui = (root / "app" / "ui.py").read_text()
    handlers = (root / "app" / "handlers.py").read_text()
    assert '"Периоды", "settings:billing_cycles"' in ui
    assert '"Отчёт", "settings:reports"' in ui
    assert '"Бекап", "settings:backups"' in ui
    assert "█" not in handlers and "░" not in handlers
    assert "Ссылка на ЛК" in ui
    assert "Время уведомления" in handlers
    assert "Ввести день и время" in ui
    assert "Ввести время вручную" not in ui
