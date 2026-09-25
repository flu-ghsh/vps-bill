from datetime import date, timedelta
from pathlib import Path

from app.db import Database

ROOT = Path(__file__).resolve().parents[1]


def test_changelog_contains_2521():
    assert "## 2.5.21" in (ROOT / "CHANGELOG.md").read_text()


def test_demo_servers_are_relative_complete_and_removable(tmp_path: Path):
    db = Database(tmp_path / "billing.db")
    base = date(2026, 9, 25)
    assert db.add_demo_servers(base) == 6
    assert db.demo_server_count() == 6

    ids = set(db.demo_server_ids())
    servers = [s for s in db.list_servers(active_only=False) if s["id"] in ids]
    assert len(servers) == 6
    assert {s["next_due"] for s in servers} == {
        (base + timedelta(days=d)).isoformat() for d in (-5, 0, 1, 3, 7, 30)
    }
    assert all(s["ip"] and s["country"] and s["tags"] and s["notes"] and s["provider"] for s in servers)
    assert all(not s["monitor_enabled"] for s in servers)

    # A real VPS must survive demo cleanup.
    real_id = db.add_server(
        name="real", provider="DemoCloud", amount_minor=100, currency="RUB",
        next_due=base.isoformat(), cycle="monthly",
    )
    assert db.delete_demo_servers() == 6
    assert db.demo_server_count() == 0
    assert db.get_server(real_id) is not None
    assert db.provider_url("DemoCloud") == "https://example.com/"


def test_demo_controls_are_present():
    ui = (ROOT / "app" / "ui.py").read_text()
    handlers = (ROOT / "app" / "handlers.py").read_text()
    install = (ROOT / "install.sh").read_text()
    cli = (ROOT / "app" / "cli.py").read_text()
    assert "Добавить демо-серверы" in ui
    assert "Удалить демо-серверы" in ui
    assert "demo:add:yes" in handlers
    assert "demo:remove:yes" in handlers
    assert "Добавить демо-серверы? [y/N]" in install
    assert 'sub.add_parser("demo-add")' in cli
    assert 'sub.add_parser("demo-remove")' in cli
