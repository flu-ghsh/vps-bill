from pathlib import Path

from app.updates import is_newer, version_tuple


def test_version_compare():
    assert version_tuple("v2.5.9") == (2, 5, 9)
    assert is_newer("2.6.0", "2.5.9")
    assert not is_newer("2.5.9", "2.5.9")


def test_v259_manual_update_bridge_and_env():
    root = Path(__file__).parents[1]
    env = (root / ".env.example").read_text()
    ui = (root / "app" / "ui.py").read_text()
    handlers = (root / "app" / "handlers.py").read_text()
    notifier = (root / "app" / "notifier.py").read_text()
    install = (root / "scripts" / "install-update-bridge.sh").read_text()
    processor = (root / "scripts" / "process-update-request.sh").read_text()
    assert "EMOJI_" not in env
    assert "Обновление" in ui
    assert "Автообновление" not in ui
    assert "update:confirm:" in handlers
    assert "timedelta(minutes=30)" in notifier
    assert "vps-bill-update-request.path" in install
    assert "vps-bill-update --file" in processor
