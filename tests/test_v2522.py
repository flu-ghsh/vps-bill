from pathlib import Path

from app.updates import create_update_request


def test_demo_names_and_button_colors():
    db_text = Path("app/db.py").read_text(encoding="utf-8")
    ui = Path("app/ui.py").read_text(encoding="utf-8")
    for name in (
        "demo-web-hel1", "demo-api-fra1", "demo-vpn-ams1",
        "demo-db-par1", "demo-backup-nyc1", "demo-monitor-lon1",
    ):
        assert name in db_text
    assert 'style="danger" if demo_present else None' in ui
    assert '"demo:add:yes")' in ui
    assert '"demo:remove:yes", style="danger")' in ui


def test_update_request_removes_old_fixed_tmp(tmp_path: Path):
    stale = tmp_path / ".request.json.tmp"
    stale.write_text("old", encoding="utf-8")
    create_update_request(tmp_path, "2.5.22")
    assert not stale.exists()
    assert (tmp_path / "request.json").exists()


def test_updater_syncs_compose_and_bridge():
    text = Path("scripts/update.sh").read_text(encoding="utf-8")
    assert 'cp -f "$TARGET/compose.yaml" "$BASE/compose.yaml"' in text
    assert 'install-update-bridge.sh' in text
