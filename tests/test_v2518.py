from pathlib import Path

from app.db import Database


def test_v2518_reminder_presets_are_10_15_20():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "app" / "ui.py").read_text(encoding="utf-8")
    assert 'preset_times = ("10:00", "15:00", "20:00")' in ui
    assert 'preset_times = ("09:00", "10:00", "12:00", "18:00")' not in ui


def test_v2518_delete_country_clears_all_non_deleted_servers(tmp_path: Path):
    db = Database(tmp_path / "billing.db")
    db.migrate()
    a = db.add_server(name="alpha", provider="X", amount_minor=100, currency="EUR", next_due="2026-10-01", cycle="monthly")
    b = db.add_server(name="beta", provider="X", amount_minor=100, currency="EUR", next_due="2026-10-01", cycle="monthly")
    db.update_server_field(a, "country", "Finland")
    db.update_server_field(b, "country", "Finland")
    assert [s["name"] for s in db.servers_with_country("Finland")] == ["alpha", "beta"]
    assert db.delete_country("Finland") == 2
    assert db.get_server(a)["country"] == ""
    assert db.get_server(b)["country"] == ""


def test_v2518_delete_tag_preserves_other_tags(tmp_path: Path):
    db = Database(tmp_path / "billing.db")
    db.migrate()
    a = db.add_server(name="alpha", provider="X", amount_minor=100, currency="EUR", next_due="2026-10-01", cycle="monthly")
    b = db.add_server(name="beta", provider="X", amount_minor=100, currency="EUR", next_due="2026-10-01", cycle="monthly")
    db.update_server_field(a, "tags", "vpn,prod")
    db.update_server_field(b, "tags", "vpn")
    assert [s["name"] for s in db.servers_with_tag("vpn")] == ["alpha", "beta"]
    assert db.delete_tag("vpn") == 2
    assert db.get_server(a)["tags"] == "prod"
    assert db.get_server(b)["tags"] == ""


def test_v2518_bot_menu_only_start_and_delete_confirmation_present():
    root = Path(__file__).resolve().parents[1]
    main = (root / "app" / "main.py").read_text(encoding="utf-8")
    ui = (root / "app" / "ui.py").read_text(encoding="utf-8")
    handlers = (root / "app" / "handlers.py").read_text(encoding="utf-8")
    assert 'BotCommand(command="start", description="Main menu")' in main
    assert 'preset_times = ("10:00", "15:00", "20:00")' in ui
    assert '"Удалить", f"dict:delete:ask:{kind}:{idx}", style="danger"' in ui
    assert 'Точно удалить?' in handlers
    assert 'поле <b>Страна</b> будет очищено' in handlers


def test_v2518_version_and_changelog():
    root = Path(__file__).resolve().parents[1]
    assert "## 2.5.18" in (root / "CHANGELOG.md").read_text()
