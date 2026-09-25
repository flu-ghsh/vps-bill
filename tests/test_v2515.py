from pathlib import Path

from app.updates import create_update_request


def test_update_request_uses_unique_tmp_and_is_atomic(tmp_path: Path):
    # A stale file with the fixed name used by old releases must not block us.
    stale = tmp_path / ".request.json.tmp"
    stale.write_text("stale", encoding="utf-8")

    request_id = create_update_request(tmp_path, "2.5.15")

    assert request_id.startswith("2.5.15-")
    assert (tmp_path / "request.json").is_file()
    assert not stale.exists()
    leftovers = [x.name for x in tmp_path.glob(".request.*.tmp") if x.name != ".request.json.tmp"]
    assert leftovers == []


def test_compose_update_requests_mount_is_explicitly_rw():
    text = Path("compose.yaml").read_text(encoding="utf-8")
    assert "/opt/vps-bill/update-requests:/app/update-requests:rw" in text


def test_runtime_permission_repair_is_present():
    update = Path("scripts/update.sh").read_text(encoding="utf-8")
    install = Path("install.sh").read_text(encoding="utf-8")
    bridge = Path("scripts/install-update-bridge.sh").read_text(encoding="utf-8")

    for text in (update, install, bridge):
        assert "10001" in text
        assert "update-requests" in text
    assert "install -d -o 10001 -g 10001 -m 0770" in update
    assert "install -d -o 10001 -g 10001 -m 0770" in install
    assert 'install -d -o "$BOT_UID" -g "$BOT_GID" -m 0770 "$REQ"' in bridge
