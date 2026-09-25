import asyncio
from pathlib import Path

from app import monitoring


def test_auto_ping_ok_reports_tcp_skipped(monkeypatch):
    async def fake_ping(ip, timeout, **kwargs):
        return True

    called = {"tcp": 0}

    async def fake_tcp(ip, port, timeout):
        called["tcp"] += 1
        return False, "timeout"

    monkeypatch.setattr(monitoring, "ping_probe", fake_ping)
    monkeypatch.setattr(monitoring, "tcp_probe_detailed", fake_tcp)

    ok, details = asyncio.run(
        monitoring.probe_host("1.2.3.4", method="auto", port=22, timeout=3)
    )
    assert ok is True
    assert details["ping"] == "ok"
    assert details["tcp"] == "skip"
    assert called["tcp"] == 0


def test_tcp_connection_refused_counts_host_reachable(monkeypatch):
    async def fake_open(*args, **kwargs):
        raise ConnectionRefusedError

    monkeypatch.setattr(asyncio, "open_connection", fake_open)
    ok, status = asyncio.run(monitoring.tcp_probe_detailed("1.2.3.4", 22, 3))
    assert ok is True
    assert status == "refused"


def test_notifier_has_truthful_tcp_skip_and_provider_on_recovery():
    source = (Path(__file__).parents[1] / "app" / "notifier.py").read_text(encoding="utf-8")
    assert 'tcp_text = "не проверялся (Ping OK)"' in source
    assert 'Хостер: {h(s.get(\'provider\') or \'-\')}' in source


def test_v2519_changelog_is_preserved():
    root = Path(__file__).resolve().parents[1]
    assert "## 2.5.19" in (root / "CHANGELOG.md").read_text()
